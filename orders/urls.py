from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("cart/", views.cart, name="cart"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/item/<int:pk>/update/", views.cart_update, name="cart_update"),
    path("cart/item/<int:pk>/remove/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("orders/", views.order_list, name="list"),
    path("orders/<int:pk>/", views.order_detail, name="detail"),
    path("orders/<int:pk>/pay/", views.order_pay, name="pay"),
    path("orders/<int:pk>/cancel/", views.order_cancel, name="cancel"),
    path("seller/orders/", views.seller_list, name="seller_list"),
    path("seller/orders/item/<int:pk>/update/", views.seller_item_update, name="seller_item_update"),
]
