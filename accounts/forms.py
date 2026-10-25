from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
    UserCreationForm,
)
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from core.forms import BootstrapFormMixin

from .models import Role, SellerProfile, UserProfile

User = get_user_model()


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """Sign in with either username or email address."""

    username = forms.CharField(
        label=_("Username or email"),
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    def clean(self):
        identifier = self.cleaned_data.get("username")
        if identifier and "@" in identifier:
            match = User.objects.filter(email__iexact=identifier.strip()).first()
            if match is not None:
                self.cleaned_data["username"] = match.get_username()
        return super().clean()


class BaseRegistrationForm(BootstrapFormMixin, UserCreationForm):
    role = None  # set by subclasses

    full_name = forms.CharField(label=_("Full name"), max_length=150)
    phone_number = forms.CharField(label=_("Phone number"), max_length=20, required=False)

    # Show the fields in a natural order (names first, passwords last).
    field_order = [
        "full_name", "username", "email", "phone_number",
        "shop_name", "shop_description", "business_name",
        "password1", "password2",
    ]

    class Meta:
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email address already exists."))
        return email

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.role
        user.email = self.cleaned_data["email"]
        user.save()
        profile = user.profile
        profile.full_name = self.cleaned_data["full_name"]
        profile.phone_number = self.cleaned_data.get("phone_number", "")
        profile.save()
        return user


class CustomerRegistrationForm(BaseRegistrationForm):
    role = Role.CUSTOMER


class SellerRegistrationForm(BaseRegistrationForm):
    role = Role.SELLER

    shop_name = forms.CharField(label=_("Shop name"), max_length=80)
    shop_description = forms.CharField(
        label=_("Shop description"),
        max_length=1500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Tell customers what you sell."),
    )
    business_name = forms.CharField(
        label=_("Registered business name"), max_length=150, required=False
    )

    def clean_shop_name(self):
        shop_name = self.cleaned_data["shop_name"].strip()
        if SellerProfile.objects.filter(shop_name__iexact=shop_name).exists():
            raise forms.ValidationError(_("This shop name is already taken."))
        return shop_name

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=commit)
        SellerProfile.objects.create(
            user=user,
            shop_name=self.cleaned_data["shop_name"],
            description=self.cleaned_data.get("shop_description", ""),
            business_name=self.cleaned_data.get("business_name", ""),
        )
        return user


class UserProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("full_name", "phone_number", "location", "avatar")
        widgets = {"avatar": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"})}


class SellerProfileForm(BootstrapFormMixin, forms.ModelForm):
    """Seller-editable shop settings. Approval status is deliberately excluded."""

    class Meta:
        model = SellerProfile
        fields = (
            "shop_name",
            "description",
            "logo",
            "business_name",
            "business_address",
            "business_registration_number",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "logo": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
        }


class StyledPasswordResetForm(BootstrapFormMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(BootstrapFormMixin, SetPasswordForm):
    pass


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass

class PayoutAccountForm(BootstrapFormMixin, forms.Form):
    """Seller bank account. The name is looked up and verified with the payment provider."""

    bank = forms.ChoiceField(label=_("Bank"))
    account_number = forms.RegexField(
        label=_("Account number"),
        regex=r"^\d{10}$",
        max_length=10,
        error_messages={"invalid": _("Enter the 10-digit account number.")},
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )

    def __init__(self, *args, banks=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank"].choices = [("", _("Choose your bank"))] + list(banks)
