from django.contrib import admin

from .models import ProductRequest


@admin.register(ProductRequest)
class ProductRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "customer", "seller", "quantity", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("product__name", "customer__username", "seller__shop_name")
    readonly_fields = ("customer", "seller", "product", "created_at", "updated_at")
