from django.contrib import admin, messages

from . import services
from .models import Cart, CartItem, Order, OrderItem, Payment


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product", "seller", "product_name", "seller_name", "unit_price", "quantity",
        "commission_rate", "commission_amount", "seller_earnings",
    )


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    readonly_fields = ("reference", "provider", "amount", "currency", "status", "paid_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer", "status", "total_amount", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("reference", "customer__username", "customer__email", "shipping_name")
    readonly_fields = ("reference", "customer", "total_amount", "currency", "created_at", "updated_at")
    inlines = [OrderItemInline, PaymentInline]
    actions = ["record_refund"]

    @admin.action(description="Record refund (only AFTER refunding the customer in the Paystack dashboard)")
    def record_refund(self, request, queryset):
        done = 0
        for order in queryset:
            try:
                services.record_refund(order)
            except services.PaymentError as error:
                self.message_user(request, f"{order.reference}: {error}", level=messages.WARNING)
            else:
                done += 1
        if done:
            self.message_user(request, f"{done} order(s) marked as refunded.")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "order", "provider", "amount", "currency", "status", "paid_at")
    list_filter = ("status", "provider")
    search_fields = ("reference", "order__reference")
    readonly_fields = ("order", "reference", "provider", "amount", "currency", "created_at", "paid_at")


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("product_name", "seller_name", "quantity", "unit_price", "fulfillment_status")
    list_filter = ("fulfillment_status",)
    search_fields = ("product_name", "seller_name", "order__reference")
    readonly_fields = (
        "order", "product", "seller", "product_name", "seller_name", "unit_price", "quantity",
        "commission_rate", "commission_amount", "seller_earnings",
    )


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("user", "updated_at")
    search_fields = ("user__username",)
    inlines = [CartItemInline]
