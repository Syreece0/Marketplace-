from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from .models import Notification


@login_required
def notification_list(request):
    # Always filtered by the current user: nobody can read another user's notifications.
    queryset = Notification.objects.filter(user=request.user)
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page_obj": page})


@login_required
@require_POST
def mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    return redirect("notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    messages.success(request, _("All notifications marked as read."))
    return redirect("notifications:list")


@login_required
@require_GET
def unread_count(request):
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({"count": count})
