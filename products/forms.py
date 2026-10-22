from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from core.forms import BootstrapFormMixin

from .models import Category, Product, ProductImage, Report, Review

IMAGE_ACCEPT = {"accept": "image/jpeg,image/png,image/webp"}


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    """Seller-editable product fields. Status and seller are never form fields,
    which prevents mass-assignment of approval status or ownership."""

    class Meta:
        model = Product
        fields = ("name", "category", "description", "price", "quantity", "condition", "image")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "price": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "quantity": forms.NumberInput(attrs={"min": "0"}),
            "image": forms.FileInput(attrs=IMAGE_ACCEPT),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True)
        self.fields["image"].help_text = _("JPG, PNG or WebP. Maximum %(mb)s MB.") % {
            "mb": settings.MAX_IMAGE_UPLOAD_MB
        }

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price <= Decimal("0"):
            raise forms.ValidationError(_("Price must be greater than zero."))
        return price


class ProductImageForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ("image", "alt_text")
        widgets = {"image": forms.FileInput(attrs=IMAGE_ACCEPT)}

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product

    def clean(self):
        cleaned = super().clean()
        if self.product is not None and self.product.images.count() >= settings.MAX_GALLERY_IMAGES:
            raise forms.ValidationError(
                _("A product can have at most %(n)s additional images.")
                % {"n": settings.MAX_GALLERY_IMAGES}
            )
        return cleaned


class ReviewForm(BootstrapFormMixin, forms.ModelForm):
    rating = forms.TypedChoiceField(
        label=_("Rating"),
        choices=[(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")],
        coerce=int,
    )

    class Meta:
        model = Review
        fields = ("rating", "comment")
        widgets = {"comment": forms.Textarea(attrs={"rows": 3})}


class ReportForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Report
        fields = ("reason", "details")
        widgets = {"details": forms.Textarea(attrs={"rows": 3})}


class ProductFilterForm(BootstrapFormMixin, forms.Form):
    """GET form used on the marketplace page. Invalid values are simply ignored."""

    SORT_CHOICES = [
        ("newest", _("Newest")),
        ("price_asc", _("Price: low to high")),
        ("price_desc", _("Price: high to low")),
        ("name", _("Name A-Z")),
    ]

    q = forms.CharField(label=_("Search"), required=False, max_length=100)
    category = forms.ModelChoiceField(
        label=_("Category"),
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label=_("All categories"),
    )
    condition = forms.ChoiceField(
        label=_("Condition"),
        required=False,
        choices=[("", _("Any condition"))] + list(Product.Condition.choices),
    )
    min_price = forms.DecimalField(label=_("Min price"), required=False, min_value=0)
    max_price = forms.DecimalField(label=_("Max price"), required=False, min_value=0)
    in_stock = forms.BooleanField(label=_("In stock only"), required=False)
    sort = forms.ChoiceField(label=_("Sort by"), required=False, choices=SORT_CHOICES)
