"""Factories and helpers shared by the automated tests."""
import io
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import Role, SellerProfile, SellerStatus
from products.models import Category, Product

User = get_user_model()
PASSWORD = "Str0ng-Test-Pass!42"

_MEDIA_ROOT = tempfile.mkdtemp(prefix="marketplace-test-media-")


def make_customer(username="customer", **extra):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password=PASSWORD, role=Role.CUSTOMER, **extra
    )


def make_seller(username="seller", shop_name=None, status=SellerStatus.APPROVED):
    user = User.objects.create_user(
        username=username, email=f"{username}@example.com", password=PASSWORD, role=Role.SELLER
    )
    profile = SellerProfile.objects.create(
        user=user, shop_name=shop_name or f"{username.title()} Shop", status=status
    )
    return user, profile


def make_admin(username="boss"):
    return User.objects.create_user(
        username=username, email=f"{username}@example.com", password=PASSWORD, role=Role.ADMIN
    )


def make_category(name="Gadgets", **extra):
    return Category.objects.create(name=name, **extra)


def make_product(seller_profile, category=None, **extra):
    category = category or Category.objects.get_or_create(name="Gadgets")[0]
    defaults = {
        "name": "Test product",
        "description": "A product used in tests.",
        "price": Decimal("1000.00"),
        "quantity": 10,
        "status": Product.Status.PUBLISHED,
    }
    defaults.update(extra)
    return Product.objects.create(seller=seller_profile, category=category, **defaults)


def image_upload(name="photo.png", size=(40, 30), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 120, 30)).save(buffer, format=fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f"image/{fmt.lower()}")


@override_settings(
    MEDIA_ROOT=_MEDIA_ROOT,
    PAYMENT_GATEWAY="test",
    COMMISSION_PERCENT=Decimal("10"),
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class BaseTestCase(TestCase):
    """TestCase that writes uploads to a temporary directory and has handy logins."""
    
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA_ROOT, ignore_errors=True)

    def login(self, user):
        self.assertTrue(self.client.login(username=user.username, password=PASSWORD))
        return user
