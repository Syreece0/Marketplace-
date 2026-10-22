from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from core.forms import BootstrapFormMixin


class QuantityForm(BootstrapFormMixin, forms.Form):
    quantity = forms.IntegerField(label=_("Quantity"), min_value=1, max_value=settings.MAX_CART_ITEM_QUANTITY)


class CartUpdateForm(BootstrapFormMixin, forms.Form):
    """Quantity 0 removes the item."""

    quantity = forms.IntegerField(label=_("Quantity"), min_value=0, max_value=settings.MAX_CART_ITEM_QUANTITY)


class CheckoutForm(BootstrapFormMixin, forms.Form):
    shipping_name = forms.CharField(label=_("Recipient name"), max_length=150)
    shipping_phone = forms.CharField(label=_("Phone number"), max_length=20)
    shipping_address = forms.CharField(label=_("Delivery address"), max_length=255)
    shipping_city = forms.CharField(label=_("City"), max_length=100)
    notes = forms.CharField(
        label=_("Order notes"),
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_("Optional. For example delivery instructions."),
    )
