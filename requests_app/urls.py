from django.urls import path

from . import views

app_name = "requests_app"

urlpatterns = [
    path("requests/", views.customer_list, name="customer_list"),
    path("requests/new/<slug:slug>/", views.request_create, name="create"),
    path("requests/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("requests/<int:pk>/cancel/", views.customer_cancel, name="customer_cancel"),
    path("seller/requests/", views.seller_list, name="seller_list"),
    path("seller/requests/<int:pk>/", views.seller_detail, name="seller_detail"),
    path("seller/requests/<int:pk>/respond/", views.seller_respond, name="seller_respond"),
]
