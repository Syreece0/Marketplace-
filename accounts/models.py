from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.utils import unique_slugify
from core.validators import validate_image_file


class Role(models.TextChoices):
    CUSTOMER = "customer", _("Customer")
    SELLER = "seller", _("Seller")
    ADMIN = "admin", _("Administrator")


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Accounts made with ``createsuperuser`` are marketplace administrators.
        extra_fields.setdefault("role", Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Single user model for customers, sellers and administrators.

    The ``role`` field is the one source of truth for what an account is.
    Use the ``is_*`` properties instead of comparing strings in views.
    """

    email = models.EmailField(_("email address"), unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)

    objects = UserManager()

    class Meta:
        ordering = ["-date_joined"]
        indexes = [models.Index(fields=["role", "is_active"])]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    # -- role helpers -----------------------------------------------------
    @property
    def is_customer(self):
        return self.is_active and self.role == Role.CUSTOMER

    @property
    def is_seller(self):
        return self.is_active and self.role == Role.SELLER

    @property
    def is_marketplace_admin(self):
        """Marketplace administrators only. Ordinary ``is_staff`` is not enough."""
        return self.is_active and (self.is_superuser or self.role == Role.ADMIN)

    @property
    def is_approved_seller(self):
        profile = getattr(self, "seller_profile", None)
        return bool(
            self.is_seller and profile is not None and profile.status == SellerStatus.APPROVED
        )

    @property
    def display_name(self):
        profile = getattr(self, "profile", None)
        if profile is not None and profile.full_name:
            return profile.full_name
        return self.get_full_name() or self.username


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    full_name = models.CharField(_("full name"), max_length=150, blank=True)
    phone_number = models.CharField(_("phone number"), max_length=20, blank=True)
    location = models.CharField(_("location"), max_length=120, blank=True)
    avatar = models.ImageField(
        _("profile picture"), upload_to="avatars/%Y/%m/", blank=True, validators=[validate_image_file]
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user.username}"


class SellerStatus(models.TextChoices):
    PENDING = "pending", _("Pending approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    SUSPENDED = "suspended", _("Suspended")


class SellerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="seller_profile")
    shop_name = models.CharField(_("shop name"), max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField(_("shop description"), max_length=1500, blank=True)
    logo = models.ImageField(
        _("shop logo"), upload_to="shop_logos/%Y/%m/", blank=True, validators=[validate_image_file]
    )
    status = models.CharField(
        max_length=20, choices=SellerStatus.choices, default=SellerStatus.PENDING
    )
    status_note = models.CharField(
        _("note from administrator"), max_length=300, blank=True,
        help_text=_("Shown to the seller, e.g. the reason for a rejection."),
    )
    business_name = models.CharField(_("registered business name"), max_length=150, blank=True)
    business_address = models.CharField(_("business address"), max_length=250, blank=True)
    business_registration_number = models.CharField(
        _("business registration number"), max_length=60, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["shop_name"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return self.shop_name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.shop_name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("products:shop", kwargs={"slug": self.slug})

    @property
    def is_approved(self):
        return self.status == SellerStatus.APPROVED


# Payout account. Set through the verified payout page, never typed in directly.
    bank_code = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(_("bank"), max_length=120, blank=True)
    account_number = models.CharField(_("account number"), max_length=20, blank=True)
    account_name = models.CharField(_("account name"), max_length=150, blank=True)
    paystack_subaccount_code = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["shop_name"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return self.shop_name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.shop_name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("products:shop", kwargs={"slug": self.slug})

    @property
    def is_approved(self):
        return self.status == SellerStatus.APPROVED

    @property
    def can_receive_payouts(self):
        return bool(self.paystack_subaccount_code)

    @property
    def masked_account_number(self):
        number = self.account_number or ""
        return ("*" * max(len(number) - 4, 0)) + number[-4:]
