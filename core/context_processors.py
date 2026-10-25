"""Template context available on every page."""
from django.conf import settings


def site(request):
    context = {
        "SITE_NAME": settings.SITE_NAME,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
        "PAYMENT_IS_TEST": settings.PAYMENT_GATEWAY == "test",
        "COMMISSION_PERCENT": format(settings.COMMISSION_PERCENT.normalize(), "f"),
        "unread_notifications": 0,
        "cart_count": 0,
    }
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        # Imported lazily to avoid circular imports at start-up.
        from notifications.models import Notification

        context["unread_notifications"] = Notification.objects.filter(
            user=user, is_read=False
        ).count()
        if user.is_customer:
            from orders.models import CartItem

            context["cart_count"] = sum(
                CartItem.objects.filter(cart__user=user).values_list("quantity", flat=True)
            )
    return context
