from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import SellerProfile, User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "role", "is_active", "is_staff", "date_joined")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "profile__full_name")
    inlines = [UserProfileInline]
    fieldsets = DjangoUserAdmin.fieldsets + (("Marketplace", {"fields": ("role",)}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Marketplace", {"fields": ("email", "role")}),
    )


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("shop_name", "user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("shop_name", "user__username", "user__email", "business_name")
    readonly_fields = ("slug", "created_at", "updated_at")
    actions = ["approve_sellers", "suspend_sellers"]

    @admin.action(description="Approve selected sellers")
    def approve_sellers(self, request, queryset):
        queryset.update(status="approved")

    @admin.action(description="Suspend selected sellers")
    def suspend_sellers(self, request, queryset):
        queryset.update(status="suspended")
