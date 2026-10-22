from django.urls import path

from . import views

app_name = "wishlist"

urlpatterns = [
    path("wishlist/", views.wishlist_list, name="list"),
    path("wishlist/toggle/<int:product_id>/", views.toggle, name="toggle"),
    path("wishlist/remove/<int:pk>/", views.remove, name="remove"),
]
