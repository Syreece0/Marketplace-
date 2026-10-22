"""Business rules for carts, orders and payments.

All prices are read from the database on the server; nothing price-related is
ever trusted from the browser. Multi-step operations run in transactions.
"""
import uuid
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from core.utils import audit_logger
from notifications.services import notify
from products.models import Product

from .gateways import get_gateway
from .models import Cart, CartItem, Order, OrderItem, Payment


class CartError(Exception):
    """Raised with a user-presentable message."""


class CheckoutError(Exception):
    """Raised with a user-presentable message."""


class PaymentError(Exception):
    """Raised with a user-presentable message."""


class FulfillmentError(Exception):
    """Raised with a user-presentable message."""


# ---------------------------------------------------------------- cart ----
def get_cart(user):
    cart, _created = Cart.objects.get_or_create(user=user)
    return cart


def _validate_quantity(product, quantity):
    if quantity < 1:
        raise CartError(_("Quantity must be at least 1."))
    if quantity > settings.MAX_CART_ITEM_QUANTITY:
        raise CartError(
            _("You can order at most %(n)s of one product at a time.")
            % {"n": settings.MAX_CART_ITEM_QUANTITY}
        )
    if quantity > product.quantity:
        raise CartError(
            _("Only %(n)s of \"%(name)s\" are available.")
            % {"n": product.quantity, "name": product.name}
        )


def add_to_cart(user, product, quantity):
    if not product.is_purchasable:
        raise CartError(_("This product is not available right now."))
    cart = get_cart(user)
    with transaction.atomic():
        item = CartItem.objects.select_for_update().filter(cart=cart, product=product).first()
        new_quantity = (item.quantity if item else 0) + quantity
        _validate_quantity(product, new_quantity)
        if item:
            item.quantity = new_quantity
            item.save(update_fields=["quantity"])
        else:
            item = CartItem.objects.create(cart=cart, product=product, quantity=new_quantity)
    return item


def update_cart_item(item, quantity):
    """Set an item's quantity. A quantity of 0 removes the item."""
    if quantity == 0:
        item.delete()
        return None
    if not item.product.is_purchasable:
        raise CartError(_("This product is not available right now."))
    _validate_quantity(item.product, quantity)
    item.quantity = quantity
    item.save(update_fields=["quantity"])
    return item


# ------------------------------------------------------------ checkout ----
@transaction.atomic
def create_order(user, shipping):
    """Turn the user's cart into an order.

    ``shipping`` is a dict with shipping_name, shipping_phone,
    shipping_address, shipping_city and (optionally) notes. Stock is reserved
    immediately with a guarded UPDATE, so two buyers can never both purchase
    the last unit. Any failure rolls the whole operation back.
    """
    cart = get_cart(user)
    cart_items = list(cart.items.all())
    if not cart_items:
        raise CheckoutError(_("Your cart is empty."))

    products = {
        product.pk: product
        for product in Product.objects.select_for_update(of=("self",))
        .select_related("seller", "seller__user", "category")
        .filter(pk__in=[item.product_id for item in cart_items])
    }

    lines = []
    total = 0
    for cart_item in cart_items:
        product = products.get(cart_item.product_id)
        if product is None or not product.is_purchasable:
            raise CheckoutError(
                _("\"%(name)s\" is no longer available. Please update your cart.")
                % {"name": product.name if product else _("An item")}
            )
        if cart_item.quantity > product.quantity:
            raise CheckoutError(
                _("Only %(n)s of \"%(name)s\" are available. Please update your cart.")
                % {"n": product.quantity, "name": product.name}
            )
        lines.append((product, cart_item.quantity))
        total += product.price * cart_item.quantity

    order = Order.objects.create(
        customer=user,
        total_amount=total,
        currency=settings.CURRENCY_CODE,
        shipping_name=shipping["shipping_name"],
        shipping_phone=shipping["shipping_phone"],
        shipping_address=shipping["shipping_address"],
        shipping_city=shipping["shipping_city"],
        notes=shipping.get("notes", ""),
    )
    for product, quantity in lines:
        updated = Product.objects.filter(pk=product.pk, quantity__gte=quantity).update(
            quantity=F("quantity") - quantity
        )
        if not updated:
            raise CheckoutError(
                _("\"%(name)s\" just sold out. Please update your cart.") % {"name": product.name}
            )
        OrderItem.objects.create(
            order=order,
            product=product,
            seller=product.seller,
            product_name=product.name,
            seller_name=product.seller.shop_name,
            unit_price=product.price,
            quantity=quantity,
        )

    _new_payment(order)
    cart.items.all().delete()
    audit_logger.info("Order created: %s customer_id=%s total=%s", order.reference, user.pk, total)
    notify(
        user,
        _("Order %(ref)s created. Complete payment to confirm it.") % {"ref": order.reference},
        reverse("orders:detail", kwargs={"pk": order.pk}),
    )
    return order


def _new_payment(order):
    return Payment.objects.create(
        order=order,
        reference="PAY-" + uuid.uuid4().hex[:16].upper(),
        provider=settings.PAYMENT_GATEWAY,
        amount=order.total_amount,
        currency=order.currency,
    )


# ------------------------------------------------------------- payment ----
def pay_order(order):
    """Collect payment for an order. Only unpaid orders with a pending payment qualify."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        payment = order.payments.filter(status=Payment.Status.PENDING).first()
        if order.status != Order.Status.PENDING_PAYMENT or payment is None:
            raise PaymentError(_("This order cannot be paid."))

        if get_gateway().charge(payment):
            payment.status = Payment.Status.PAID
            payment.paid_at = timezone.now()
            payment.save(update_fields=["status", "paid_at"])
            order.status = Order.Status.PAID
            order.save(update_fields=["status", "updated_at"])
            audit_logger.info("Order paid: %s payment=%s", order.reference, payment.reference)
            _notify_after_payment(order)
            return order

        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])
        _new_payment(order)  # allow another attempt
    raise PaymentError(_("Payment failed. Please try again."))


def _notify_after_payment(order):
    notify(
        order.customer,
        _("Payment received for order %(ref)s. Thank you!") % {"ref": order.reference},
        reverse("orders:detail", kwargs={"pk": order.pk}),
    )
    per_seller = defaultdict(int)
    for item in order.items.select_related("seller__user"):
        if item.seller_id:
            per_seller[item.seller] += item.quantity
    for seller, count in per_seller.items():
        notify(
            seller.user,
            _("New paid order %(ref)s with %(n)s item(s) from your shop.")
            % {"ref": order.reference, "n": count},
            reverse("orders:seller_list"),
        )


@transaction.atomic
def cancel_order(order):
    """Cancel an unpaid order and return its stock."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.Status.PENDING_PAYMENT:
        raise PaymentError(_("Only unpaid orders can be cancelled."))
    for item in order.items.all():
        if item.product_id:
            Product.objects.filter(pk=item.product_id).update(quantity=F("quantity") + item.quantity)
    order.items.update(fulfillment_status=OrderItem.Fulfillment.CANCELLED)
    order.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.CANCELLED)
    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
    audit_logger.info("Order cancelled: %s", order.reference)
    return order


# --------------------------------------------------------- fulfillment ----
_FULFILLMENT_FLOW = {
    OrderItem.Fulfillment.PENDING: {OrderItem.Fulfillment.PROCESSING},
    OrderItem.Fulfillment.PROCESSING: {OrderItem.Fulfillment.SHIPPED},
    OrderItem.Fulfillment.SHIPPED: {OrderItem.Fulfillment.DELIVERED},
}


@transaction.atomic
def update_fulfillment(item, new_status, seller):
    """Let a seller advance their own item through the fulfilment flow."""
    item = OrderItem.objects.select_for_update().select_related("order").get(pk=item.pk)
    if item.seller_id != seller.pk:
        raise FulfillmentError(_("You can only update items from your own shop."))
    if item.order.status != Order.Status.PAID:
        raise FulfillmentError(_("Only paid orders can be fulfilled."))
    if new_status not in _FULFILLMENT_FLOW.get(item.fulfillment_status, set()):
        raise FulfillmentError(_("That status change is not allowed."))
    item.fulfillment_status = new_status
    item.save(update_fields=["fulfillment_status"])
    notify(
        item.order.customer,
        _("Your item \"%(name)s\" in order %(ref)s is now: %(status)s.")
        % {
            "name": item.product_name,
            "ref": item.order.reference,
            "status": item.get_fulfillment_status_display(),
        },
        reverse("orders:detail", kwargs={"pk": item.order_id}),
    )
    return item
