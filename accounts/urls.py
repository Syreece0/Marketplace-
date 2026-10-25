from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_customer, name="register"),
    path("register/seller/", views.register_seller, name="register_seller"),
    path("login/", views.UserLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),  # POST only (Django 5)
    path("signed-out/", views.logged_out, name="logged_out"),
    path("password-reset/", views.UserPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        views.UserPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.UserPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        views.UserPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("password-change/", views.UserPasswordChangeView.as_view(), name="password_change"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("shop/settings/", views.shop_settings, name="shop_settings"),
    path("shop/payouts/", views.payout_settings, name="payout_settings"),
]
