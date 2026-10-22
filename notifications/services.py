from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Notification


def notify(user, message, url=""):
    """Create an in-app notification. ``url`` must be an internal path."""
    if user is None:
        return None
    if url and not url.startswith("/"):
        url = ""
    return Notification.objects.create(user=user, message=message[:255], url=url)


def notify_admins(message, url=""):
    """Notify every active marketplace administrator."""
    User = get_user_model()
    admins = User.objects.filter(is_active=True).filter(Q(role="admin") | Q(is_superuser=True))
    for admin_user in admins:
        notify(admin_user, message, url)
