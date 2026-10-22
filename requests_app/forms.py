from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import BootstrapFormMixin

from .models import ProductRequest


class ProductRequestForm(BootstrapFormMixin, forms.ModelForm):
    """Customer-editable fields only. Customer, seller, product and status are
    set by the view, never read from the submitted form."""

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product

    class Meta:
        model = ProductRequest
        fields = ("quantity", "message")
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": "1"}),
            "message": forms.Textarea(
                attrs={"rows": 3, "placeholder": _("Ask the seller anything about this item...")}
            ),
        }

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < 1:
            raise forms.ValidationError(_("Quantity must be at least 1."))
        if self.product is not None and quantity > self.product.quantity:
            raise forms.ValidationError(
                _("Only %(n)s available.") % {"n": self.product.quantity}
            )
        return quantity


class SellerResponseForm(BootstrapFormMixin, forms.Form):
    ACTIONS = {
        "accept": ProductRequest.Status.ACCEPTED,
        "reject": ProductRequest.Status.REJECTED,
        "complete": ProductRequest.Status.COMPLETED,
    }

    action = forms.ChoiceField(choices=[(key, key) for key in ACTIONS], widget=forms.HiddenInput)
    response = forms.CharField(
        label=_("Message to the customer"),
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
