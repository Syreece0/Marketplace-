from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class ProductRequest(models.Model):
    """A customer's enquiry/request to a seller about a specific product."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    # Allowed status changes. Customers may only cancel; sellers handle the rest.
    TRANSITIONS = {
        Status.PENDING: {Status.ACCEPTED, Status.REJECTED, Status.CANCELLED},
        Status.ACCEPTED: {Status.COMPLETED, Status.CANCELLED},
    }
    SELLER_ACTIONS = {Status.ACCEPTED, Status.REJECTED, Status.COMPLETED}
    CUSTOMER_ACTIONS = {Status.CANCELLED}

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="product_requests"
    )
    seller = models.ForeignKey(
        "accounts.SellerProfile", on_delete=models.CASCADE, related_name="incoming_requests"
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="requests"
    )
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    message = models.TextField(max_length=1000, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    seller_response = models.TextField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="request_quantity_gte_1"),
            # A customer cannot have two open requests for the same product.
            models.UniqueConstraint(
                fields=["customer", "product"],
                condition=Q(status="pending"),
                name="one_pending_request_per_customer_product",
            ),
        ]
        indexes = [
            models.Index(fields=["seller", "status"]),
            models.Index(fields=["customer", "status"]),
        ]

    def __str__(self):
        return f"Request #{self.pk} for {self.product_id}"

    def clean(self):
        super().clean()
        if self.product_id and self.seller_id and self.product.seller_id != self.seller_id:
            raise ValidationError(_("The seller must be the owner of the requested product."))

    def can_transition_to(self, new_status):
        return new_status in self.TRANSITIONS.get(self.status, set())

    def transition_to(self, new_status, response=""):
        """Change status if the transition is allowed, otherwise raise ValidationError."""
        if not self.can_transition_to(new_status):
            raise ValidationError(_("That status change is not allowed."))
        self.status = new_status
        if response:
            self.seller_response = response
        self.save(update_fields=["status", "seller_response", "updated_at"])
