from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("dashboard/", views.home, name="home"),
    path("dashboard/customer/", views.customer_dashboard, name="customer"),
    path("dashboard/seller/", views.seller_dashboard, name="seller"),
    path("manage/", views.admin_dashboard, name="admin"),
    path("manage/users/", views.manage_users, name="users"),
    path("manage/users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("manage/sellers/", views.manage_sellers, name="sellers"),
    path("manage/sellers/<int:pk>/status/", views.seller_set_status, name="seller_status"),
    path("manage/products/", views.manage_products, name="products"),
    path("manage/products/<int:pk>/moderate/", views.product_moderate, name="product_moderate"),
    path("manage/categories/", views.manage_categories, name="categories"),
    path("manage/categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("manage/categories/<int:pk>/toggle/", views.category_toggle, name="category_toggle"),
    path("manage/requests/", views.manage_requests, name="requests"),
    path("manage/orders/", views.manage_orders, name="orders"),
    path("manage/orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("manage/reports/", views.manage_reports, name="reports"),
    path("manage/reports/<int:pk>/update/", views.report_update, name="report_update"),
    path("manage/reviews/", views.manage_reviews, name="reviews"),
    path("manage/reviews/<int:pk>/toggle/", views.review_toggle, name="review_toggle"),
    path("manage/statistics/", views.statistics, name="statistics"),
]
