"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("", include("products.urls")),
    path("", include("wishlist.urls")),
    path("", include("requests_app.urls")),
    path("", include("orders.urls")),
    path("notifications/", include("notifications.urls")),
    path("", include("dashboard.urls")),
]

if settings.DEBUG:
    # Serve uploaded media during development only. In production use
    # dedicated storage (see README.md, "Deployment").
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "core.views.permission_denied"
handler404 = "core.views.page_not_found"
handler500 = "core.views.server_error"
