from django.contrib import admin

from .models import Category, Product, ProductImage, Report, Review


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "seller", "category", "price", "quantity", "status", "availability", "created_at")
    list_filter = ("status", "availability", "condition", "category")
    search_fields = ("name", "seller__shop_name", "description")
    readonly_fields = ("slug", "created_at", "updated_at")
    inlines = [ProductImageInline]
    actions = ["publish", "reject"]

    @admin.action(description="Publish selected products")
    def publish(self, request, queryset):
        queryset.update(status=Product.Status.PUBLISHED, rejection_reason="")

    @admin.action(description="Reject selected products")
    def reject(self, request, queryset):
        queryset.update(status=Product.Status.REJECTED)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("product", "position", "created_at")
    raw_id_fields = ("product",)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "customer", "rating", "is_visible", "created_at")
    list_filter = ("is_visible", "rating")
    search_fields = ("product__name", "customer__username", "comment")
    readonly_fields = ("product", "customer", "order", "rating", "comment", "created_at")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "reporter", "reason", "status", "created_at")
    list_filter = ("status", "reason")
    search_fields = ("product__name", "reporter__username", "details")
    readonly_fields = ("reporter", "product", "reason", "details", "created_at", "updated_at")
