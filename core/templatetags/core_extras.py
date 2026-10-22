"""Template helpers used across the site."""
from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings

register = template.Library()

_TONES = {
    "success": {
        "approved", "published", "paid", "accepted", "delivered", "resolved",
        "available", "completed", "shipped", "visible", "active",
    },
    "warning": {"pending", "reviewing", "processing", "draft", "open", "pending_payment"},
    "danger": {
        "rejected", "cancelled", "suspended", "failed", "dismissed", "unavailable",
        "hidden", "refunded", "inactive",
    },
}


@register.filter
def money(value):
    """Format a number as currency, e.g. ₦1,500.00."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return ""
    return f"{settings.CURRENCY_SYMBOL}{amount:,.2f}"


@register.filter
def status_tone(value):
    """Map a status value to a visual tone: success / warning / danger / neutral."""
    key = str(value).lower()
    for tone, values in _TONES.items():
        if key in values:
            return tone
    return "neutral"


@register.filter
def multiply(value, arg):
    try:
        return Decimal(value) * Decimal(arg)
    except (InvalidOperation, TypeError, ValueError):
        return ""


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Return the current query string with some parameters replaced.

    Used by pagination links so filters and search terms are preserved.
    """
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        query[key] = value
    return query.urlencode()
