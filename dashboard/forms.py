from django import forms
from django.utils.translation import gettext_lazy as _

from accounts.models import SellerStatus
from core.forms import BootstrapFormMixin
from products.models import Category, Report


class CategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description", "image", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "image": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }


class SellerStatusForm(BootstrapFormMixin, forms.Form):
    status = forms.ChoiceField(choices=SellerStatus.choices)
    note = forms.CharField(label=_("Note to seller"), required=False, max_length=300)


class ProductModerationForm(BootstrapFormMixin, forms.Form):
    ACTIONS = [("publish", _("Publish")), ("reject", _("Reject")), ("unpublish", _("Send back to pending"))]

    action = forms.ChoiceField(choices=ACTIONS)
    reason = forms.CharField(label=_("Reason (shown to seller)"), required=False, max_length=300)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") == "reject" and not cleaned.get("reason"):
            self.add_error("reason", _("Please give the seller a reason for the rejection."))
        return cleaned


class ReportUpdateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Report
        fields = ("status", "admin_notes")
        widgets = {"admin_notes": forms.Textarea(attrs={"rows": 2})}
