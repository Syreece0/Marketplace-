import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.permissions import approved_seller_required, customer_required
from core.utils import audit_logger, safe_next_url
from products.models import Product

from . import paystack, services
from .forms import CartUpdateForm, CheckoutForm, QuantityForm
from .gateways import get_gateway
from .models import CartItem, Order, OrderItem, Payment


# ----------------------------------------------------------------- cart ----
@customer_required
def cart(request):
    cart_obj = services.get_cart(request.user)
    items = cart_obj.get_items()
    total = sum(item.line_total for item in items)
    has_unavailable = any(not item.product.is_purchasable for item in items)
    return render(
        request,
        "orders/cart.html",
        {"items": items, "total": total, "has_unavailable": has_unavailable},
    )


@customer_required
@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product.objects.public(), pk=product_id)
    form = QuantityForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Please enter a valid quantity."))
        return redirect(safe_next_url(request, product.get_absolute_url()))
    try:
        services.add_to_cart(request.user, product, form.cleaned_data["quantity"])
    except services.CartError as error:
        messages.error(request, str(error))
        return redirect(safe_next_url(request, product.get_absolute_url()))
    messages.success(request, _("\"%(name)s\" was added to your cart.") % {"name": product.name})
    return redirect("orders:cart")


@customer_required
@require_POST
def cart_update(request, pk):
    item = get_object_or_404(CartItem.objects.select_related("product"), pk=pk, cart__user=request.user)
    form = CartUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Please enter a valid quantity."))
        return redirect("orders:cart")
    try:
        services.update_cart_item(item, form.cleaned_data["quantity"])
    except services.CartError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, _("Your cart has been updated."))
    return redirect("orders:cart")


@customer_required
@require_POST
def cart_remove(request, pk):
    item = get_object_or_404(CartItem, pk=pk, cart__user=request.user)
    item.delete()
    messages.success(request, _("Item removed from your cart."))
    return redirect("orders:cart")


# ------------------------------------------------------------- checkout ----
@customer_required
def checkout(request):
    cart_obj = services.get_cart(request.user)
    items = cart_obj.get_items()
    if not items:
        messages.info(request, _("Your cart is empty."))
        return redirect("orders:cart")
    total = sum(item.line_total for item in items)

    profile = request.user.profile
    initial = {"shipping_name": profile.full_name, "shipping_phone": profile.phone_number}
    form = CheckoutForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            order = services.create_order(request.user, form.cleaned_data)
        except services.CheckoutError as error:
            messages.error(request, str(error))
            return redirect("orders:cart")
        messages.success(request, _("Your order has been created. Please complete payment."))
        return redirect("orders:detail", pk=order.pk)
    return render(request, "orders/checkout.html", {"form": form, "items": items, "total": total})


# --------------------------------------------------------------- orders ----
@customer_required
def order_list(request):
    orders = Order.objects.filter(customer=request.user).prefetch_related("items")
    status = request.GET.get("status", "")
    if status in Order.Status.values:
        orders = orders.filter(status=status)
    page = Paginator(orders, 10).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/order_list.html",
        {"page_obj": page, "status": status, "statuses": Order.Status.choices},
    )


@customer_required
def order_detail(request, pk):
    # Scoped to the logged-in customer: other customers' orders return 404.
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "payments"), pk=pk, customer=request.user
    )
    from products.models import Review

    reviewed = set(
        Review.objects.filter(customer=request.user, product__in=[i.product_id for i in order.items.all() if i.product_id])
        .values_list("product_id", flat=True)
    )
    return render(request, "orders/order_detail.html", {"order": order, "reviewed_ids": reviewed})


@customer_required
@require_POST
def order_pay(request, pk):
    order = get_object_or_404(Order, pk=pk, customer=request.user)
    try:
        if get_gateway().redirect_based:
            # Real payment: send the customer to the provider's secure page.
            callback = request.build_absolute_uri(reverse("orders:payment_return"))
            return redirect(services.start_online_payment(order, callback))
        services.pay_order(order)
    except services.PaymentError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, _("Payment successful. Your order is confirmed."))
    return redirect("orders:detail", pk=order.pk)


@customer_required
def payment_return(request):
    """Where Paystack sends the customer back after paying. The outcome is always re-checked
    with Paystack; nothing in this URL is trusted."""
    reference = request.GET.get("reference") or request.GET.get("trxref") or ""
    payment = get_object_or_404(Payment, reference=reference, order__customer=request.user)
    try:
        order, outcome = services.confirm_online_payment(payment.reference)
    except services.PaymentError as error:
        messages.warning(request, str(error))
        return redirect("orders:detail", pk=payment.order_id)
    if outcome == "paid":
        messages.success(request, _("Payment successful. Your order is confirmed."))
    elif outcome == "pending":
        messages.info(request, _("Your payment is still being processed. This page will update once it is confirmed."))
    else:
        messages.error(request, _("The payment was not completed. You have not been charged. Please try again."))
    return redirect("orders:detail", pk=order.pk)


@csrf_exempt
@require_POST
def paystack_webhook(request):
    """Server-to-server notification from Paystack. Authenticated by its HMAC signature
    (not by CSRF/session), and the payment is re-verified with Paystack before it is trusted."""
    if not paystack.valid_signature(request.body, request.headers.get("x-paystack-signature", "")):
        audit_logger.warning("Rejected Paystack webhook with an invalid signature")
        return HttpResponse(status=400)
    try:
        event = json.loads(request.body.decode())
    except ValueError:
        return HttpResponse(status=400)
    if event.get("event") == "charge.success":
        reference = (event.get("data") or {}).get("reference", "")
        try:
            services.confirm_online_payment(reference)
        except services.PaymentError as error:
            # Unknown reference -> acknowledge (nothing to retry); verification failure -> ask Paystack to retry.
            if Payment.objects.filter(reference=reference).exists():
                audit_logger.warning("Webhook for %s could not be confirmed: %s", reference, error)
                return HttpResponse(status=503)
    return HttpResponse(status=200)


@customer_required
@require_POST
def order_cancel(request, pk):
    order = get_object_or_404(Order, pk=pk, customer=request.user)
    try:
        services.cancel_order(order)
    except services.PaymentError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, _("Your order has been cancelled."))
    return redirect("orders:detail", pk=order.pk)


# --------------------------------------------------------------- seller ----
@approved_seller_required
def seller_list(request):
    profile = request.user.seller_profile
    items = (
        OrderItem.objects.filter(seller=profile, order__status=Order.Status.PAID)
        .select_related("order")
        .order_by("-order__created_at", "id")
    )
    status = request.GET.get("status", "")
    if status in OrderItem.Fulfillment.values:
        items = items.filter(fulfillment_status=status)
    page = Paginator(items, 15).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/seller_orders.html",
        {"page_obj": page, "status": status, "statuses": OrderItem.Fulfillment.choices},
    )


@approved_seller_required
@require_POST
def seller_item_update(request, pk):
    item = get_object_or_404(OrderItem, pk=pk, seller=request.user.seller_profile)
    new_status = request.POST.get("status", "")
    try:
        services.update_fulfillment(item, new_status, request.user.seller_profile)
    except services.FulfillmentError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, _("Order item updated."))
    return redirect(safe_next_url(request, "orders:seller_list"))
