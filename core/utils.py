"""Small shared helpers."""
import logging

from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify

# Business and administrative actions are logged to this logger (see settings.LOGGING).
audit_logger = logging.getLogger("marketplace")


def unique_slugify(instance, value, slug_field="slug", max_length=None):
    """Return a slug for ``value`` that is unique for ``instance``'s model."""
    model = instance.__class__
    field = model._meta.get_field(slug_field)
    max_length = max_length or field.max_length
    base = slugify(value)[: max_length - 8].strip("-") or "item"
    candidate = base
    counter = 2
    queryset = model._default_manager.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    while queryset.filter(**{slug_field: candidate}).exists():
        suffix = f"-{counter}"
        candidate = f"{base[: max_length - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def safe_next_url(request, default):
    """Return the ``next`` parameter (POST or GET) only if it points at this site."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return default


def is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"
