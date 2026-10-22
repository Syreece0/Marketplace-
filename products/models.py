from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from accounts.models import SellerProfile, SellerStatus
from core.utils import unique_slugify
from core.validators import validate_image_file


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField(blank=True, max_length=500)
    image = models.ImageField(
        upload_to="categories/", blank=True, validators=[validate_image_file]
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("products:category", kwargs={"slug": self.slug})


class ProductQuerySet(models.QuerySet):
    def public(self):
        """Listings customers may see: approved, available shop, active category."""
        return self.filter(
            status=Product.Status.PUBLISHED,
            seller__status=SellerStatus.APPROVED,
            seller__user__is_active=True,
            category__is_active=True,
        )

    def purchasable(self):
        return self.public().filter(
            availability=Product.Availability.AVAILABLE, quantity__gt=0
        )


class Product(models.Model):
    class Condition(models.TextChoices):
        NEW = "new", _("New")
        LIKE_NEW = "like_new", _("Like new")
        USED = "used", _("Used")
        REFURBISHED = "refurbished", _("Refurbished")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending approval")
        PUBLISHED = "published", _("Published")
        REJECTED = "rejected", _("Rejected")

    class Availability(models.TextChoices):
        AVAILABLE = "available", _("Available")
        UNAVAILABLE = "unavailable", _("Unavailable")

    seller = models.ForeignKey(SellerProfile, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(max_length=5000)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(
        _("available quantity"), default=1, validators=[MaxValueValidator(100000)]
    )
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.NEW)
    image = models.ImageField(
        _("primary image"), upload_to="products/%Y/%m/", blank=True, validators=[validate_image_file]
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    availability = models.CharField(
        max_length=20, choices=Availability.choices, default=Availability.AVAILABLE
    )
    rejection_reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="product_price_positive"),
        ]
        indexes = [
            models.Index(fields=["status", "availability", "-created_at"]),
            models.Index(fields=["seller", "status"]),
            models.Index(fields=["category", "status"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("products:detail", kwargs={"slug": self.slug})

    @property
    def is_public(self):
        return (
            self.status == self.Status.PUBLISHED
            and self.seller.status == SellerStatus.APPROVED
            and self.seller.user.is_active
            and self.category.is_active
        )

    @property
    def in_stock(self):
        return self.availability == self.Availability.AVAILABLE and self.quantity > 0

    @property
    def is_purchasable(self):
        return self.is_public and self.in_stock


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/gallery/%Y/%m/", validators=[validate_image_file])
    alt_text = models.CharField(max_length=150, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"Image {self.pk} for {self.product_id}"


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    order = models.ForeignKey(
        "orders.Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="reviews"
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(max_length=2000, blank=True)
    is_visible = models.BooleanField(default=True, help_text=_("Hidden reviews are not shown publicly."))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["product", "customer"], name="one_review_per_customer_product"),
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5), name="review_rating_between_1_and_5"
            ),
        ]

    def __str__(self):
        return f"{self.rating}/5 for {self.product_id} by {self.customer_id}"


class Report(models.Model):
    class Reason(models.TextChoices):
        SUSPICIOUS = "suspicious", _("Suspicious or fraudulent listing")
        COUNTERFEIT = "counterfeit", _("Counterfeit item")
        INAPPROPRIATE = "inappropriate", _("Inappropriate content or behaviour")
        WRONG_INFO = "wrong_info", _("Misleading information")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        REVIEWING = "reviewing", _("Under review")
        RESOLVED = "resolved", _("Resolved")
        DISMISSED = "dismissed", _("Dismissed")

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_made"
    )
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, related_name="reports"
    )
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    admin_notes = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"Report #{self.pk} ({self.get_status_display()})"
