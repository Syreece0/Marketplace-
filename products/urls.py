from django.urls import path

from . import views

app_name = "products"

urlpatterns = [
    path("marketplace/", views.marketplace, name="list"),
    path("marketplace/category/<slug:slug>/", views.marketplace, name="category"),
    path("product/<slug:slug>/", views.product_detail, name="detail"),
    path("product/<slug:slug>/review/", views.review_create, name="review"),
    path("product/<slug:slug>/report/", views.report_create, name="report"),
    path("product/<slug:slug>/download/image/", views.download_image, name="download_image"),
    path(
        "product/<slug:slug>/download/image/<int:image_id>/",
        views.download_image,
        name="download_gallery_image",
    ),
    path("product/<slug:slug>/download/pdf/", views.download_pdf, name="download_pdf"),
    path("shop/<slug:slug>/", views.seller_shop, name="shop"),
    path("seller/products/", views.seller_product_list, name="seller_list"),
    path("seller/products/new/", views.product_create, name="create"),
    path("seller/products/<slug:slug>/edit/", views.product_edit, name="edit"),
    path("seller/products/<slug:slug>/delete/", views.product_delete, name="delete"),
    path(
        "seller/products/<slug:slug>/availability/",
        views.product_toggle_availability,
        name="toggle_availability",
    ),
    path("seller/products/<slug:slug>/images/add/", views.product_image_add, name="image_add"),
    path("seller/products/images/<int:pk>/delete/", views.product_image_delete, name="image_delete"),
]
