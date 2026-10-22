import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user_id}"

    def get_items(self):
        return list(self.items.select_related("product", "product__seller__user", "product__category"))

    @property
    def total(self):
        return sum((item.line_total for item in self.get_items()), Decimal("0.00"))


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="unique_product_per_cart"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="cartitem_quantity_gte_1"),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product_id}"

    @property
    def line_total(self):
        return self.product.price * self.quantity


def generate_order_reference():
    return "ORD-" + uuid.uuid4().hex[:10].upper()


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", _("Awaiting payment")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")

    reference = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    shipping_name = models.CharField(_("recipient name"), max_length=150)
    shipping_phone = models.CharField(_("phone number"), max_length=20)
    shipping_address = models.CharField(_("delivery address"), max_length=255)
    shipping_city = models.CharField(_("city"), max_length=100)
    notes = models.CharField(_("order notes"), max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(total_amount__gte=0), name="order_total_non_negative"),
        ]
        indexes = [models.Index(fields=["customer", "-created_at"]), models.Index(fields=["status"])]

    def __str__(self):
        return self.reference

    def save(self, *args, **kwargs):
        if not self.reference:
            reference = generate_order_reference()
            while Order.objects.filter(reference=reference).exists():
                reference = generate_order_reference()
            self.reference = reference
        super().save(*args, **kwargs)

    @property
    def can_pay(self):
        return self.status == self.Status.PENDING_PAYMENT

    @property
    def can_cancel(self):
        return self.status == self.Status.PENDING_PAYMENT


class OrderItem(models.Model):
    """One purchased line. Name, price and seller are copied at purchase time so
    order history stays accurate if the listing or shop changes later."""

    class Fulfillment(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        SHIPPED = "shipped", _("Shipped")
        DELIVERED = "delivered", _("Delivered")
        CANCELLED = "cancelled", _("Cancelled")

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "products.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="order_items"
    )
    seller = models.ForeignKey(
        "accounts.SellerProfile", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=200)
    seller_name = models.CharField(max_length=80)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    fulfillment_status = models.CharField(
        max_length=20, choices=Fulfillment.choices, default=Fulfillment.PENDING
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="orderitem_quantity_gte_1"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="orderitem_price_non_negative"),
        ]
        indexes = [models.Index(fields=["seller", "fulfillment_status"])]

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"

    @property
    def line_total(self):
        return self.unit_price * self.quantity


class Payment(models.Model):
    """Payment record. Only references and amounts are stored, never card data."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")
        REFUNDED = "refunded", _("Refunded")

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    reference = models.CharField(max_length=40, unique=True)
    provider = models.CharField(max_length=30, default="test")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["order", "status"])]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"
