"""Role-based access decorators.

Every protected view applies one of these on the *server side*; hiding links
in templates is only a convenience, never the security control.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _


def role_required(check):
    """Build a decorator: anonymous -> login page, wrong role -> 403."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


customer_required = role_required(lambda user: user.is_customer)
seller_required = role_required(lambda user: user.is_seller)
admin_required = role_required(lambda user: user.is_marketplace_admin)


def approved_seller_required(view):
    """Sellers only, and only once an administrator has approved their shop."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_seller:
            raise PermissionDenied
        if not request.user.is_approved_seller:
            messages.warning(
                request,
                _("Your seller account must be approved before you can use this page."),
            )
            return redirect("dashboard:seller")
        return view(request, *args, **kwargs)

    return wrapped
