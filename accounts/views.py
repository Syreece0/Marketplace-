from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from core.permissions import seller_required
from core.utils import audit_logger
from orders import paystack
from orders.gateways import get_gateway

from .forms import (
    CustomerRegistrationForm,
    LoginForm,
    PayoutAccountForm,
    SellerProfileForm,
    SellerRegistrationForm,
    StyledPasswordChangeForm,
    StyledPasswordResetForm,
    StyledSetPasswordForm,
    UserProfileForm,
)


def _register(request, form_class, template, success_message):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        audit_logger.info("New %s account registered: user_id=%s", user.role, user.pk)
        messages.success(request, success_message)
        return redirect("dashboard:home")
    return render(request, template, {"form": form})


def register_customer(request):
    return _register(
        request,
        CustomerRegistrationForm,
        "accounts/register_customer.html",
        _("Welcome! Your customer account has been created."),
    )


def register_seller(request):
    return _register(
        request,
        SellerRegistrationForm,
        "accounts/register_seller.html",
        _("Your seller account has been created. An administrator will review your shop soon."),
    )


class UserLoginView(LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


def logged_out(request):
    return render(request, "accounts/logged_out.html")


class UserPasswordResetView(PasswordResetView):
    form_class = StyledPasswordResetForm
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class UserPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class UserPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = StyledSetPasswordForm
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class UserPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


class UserPasswordChangeView(SuccessMessageMixin, PasswordChangeView):
    form_class = StyledPasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")
    success_message = _("Your password has been changed.")


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@login_required
def profile_edit(request):
    form = UserProfileForm(request.POST or None, request.FILES or None, instance=request.user.profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Your profile has been updated."))
        return redirect("accounts:profile")
    return render(request, "accounts/profile_edit.html", {"form": form})


@seller_required
def shop_settings(request):
    form = SellerProfileForm(
        request.POST or None, request.FILES or None, instance=request.user.seller_profile
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Your shop settings have been saved."))
        return redirect("accounts:shop_settings")
    return render(request, "accounts/shop_settings.html", {"form": form})


@seller_required
def payout_settings(request):
    """Where a seller sets the bank account their earnings are paid into."""
    profile = request.user.seller_profile
    enabled = get_gateway().requires_seller_payout_setup
    context = {"profile": profile, "payouts_enabled": enabled, "form": None}
    if not enabled:
        return render(request, "accounts/payout_settings.html", context)

    try:
        banks = paystack.list_banks()
    except paystack.PaystackError as error:
        banks = []
        messages.error(
            request,
            _("We could not load the list of banks (%(reason)s). Please try again in a moment.")
            % {"reason": error},
        )
    else:
        if not banks:
            messages.error(request, _("The bank list came back empty. Please try again in a moment."))
    form = PayoutAccountForm(request.POST or None, banks=banks)
    if request.method == "POST" and form.is_valid():
        bank_code = form.cleaned_data["bank"]
        bank_name = dict(banks).get(bank_code, "")
        number = form.cleaned_data["account_number"]
        try:
            account_name = paystack.resolve_account(number, bank_code)
            code = ""
            if profile.paystack_subaccount_code:
                try:
                    code = paystack.update_subaccount(
                        profile.paystack_subaccount_code, profile.shop_name, bank_code, number
                    )
                except paystack.PaystackError:
                    # E.g. the old code was made with test keys and live keys cannot see it.
                    code = ""
            if not code:
                code = paystack.create_subaccount(profile.shop_name, bank_code, number)
        except paystack.PaystackError as error:
            form.add_error(None, str(error))
        else:
            profile.bank_code, profile.bank_name = bank_code, bank_name
            profile.account_number, profile.account_name = number, account_name
            profile.paystack_subaccount_code = code
            profile.save(
                update_fields=["bank_code", "bank_name", "account_number", "account_name",
                               "paystack_subaccount_code", "updated_at"]
            )
            audit_logger.info("Seller %s saved a payout account", profile.pk)
            messages.success(request, _("Your payout account has been verified and saved."))
            return redirect("accounts:payout_settings")
    context["form"] = form
    return render(request, "accounts/payout_settings.html", context)
