from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.models import Role, SellerProfile, SellerStatus
from core.permissions import admin_required, customer_required, seller_required
from core.utils import audit_logger, safe_next_url
from notifications.models import Notification
from notifications.services import notify
from orders.models import CartItem, Order, OrderItem, Payment
from products.models import Category, Product, Report, Review
from requests_app.models import ProductRequest
from wishlist.models import WishlistItem

from .forms import CategoryForm, ProductModerationForm, ReportUpdateForm, SellerStatusForm

User = get_user_model()


def _page(request, queryset, per_page=15):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


# ------------------------------------------------------------------ home ----
def home(request):
    """Send each signed-in user to the dashboard for their role."""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    user = request.user
    if user.is_marketplace_admin:
        return redirect("dashboard:admin")
    if user.is_seller:
        return redirect("dashboard:seller")
    return redirect("dashboard:customer")


# -------------------------------------------------------------- customer ----
@customer_required
def customer_dashboard(request):
    user = request.user
    context = {
        "wishlist_count": WishlistItem.objects.filter(user=user).count(),
        "cart_items": CartItem.objects.filter(cart__user=user).count(),
        "order_count": Order.objects.filter(customer=user).count(),
        "open_requests": ProductRequest.objects.filter(
            customer=user, status=ProductRequest.Status.PENDING
        ).count(),
        "recent_orders": Order.objects.filter(customer=user)[:5],
        "recent_requests": ProductRequest.objects.filter(customer=user).select_related("product")[:5],
        "recent_notifications": Notification.objects.filter(user=user)[:5],
    }
    return render(request, "dashboards/customer.html", context)


# ---------------------------------------------------------------- seller ----
@seller_required
def seller_dashboard(request):
    profile = request.user.seller_profile
    context = {"shop": profile}
    if profile.status == SellerStatus.APPROVED:
        products = Product.objects.filter(seller=profile)
        paid_items = OrderItem.objects.filter(seller=profile, order__status=Order.Status.PAID)
        revenue = paid_items.aggregate(
            total=Sum(
                ExpressionWrapper(F("unit_price") * F("quantity"), output_field=DecimalField(max_digits=16, decimal_places=2))
            )
        )["total"] or Decimal("0.00")
        context.update(
            {
                "product_counts": {
                    "total": products.count(),
                    "published": products.filter(status=Product.Status.PUBLISHED).count(),
                    "pending": products.filter(status=Product.Status.PENDING).count(),
                    "rejected": products.filter(status=Product.Status.REJECTED).count(),
                },
                "pending_requests": ProductRequest.objects.filter(
                    seller=profile, status=ProductRequest.Status.PENDING
                ).count(),
                "orders_to_fulfil": paid_items.filter(
                    fulfillment_status__in=[
                        OrderItem.Fulfillment.PENDING,
                        OrderItem.Fulfillment.PROCESSING,
                    ]
                ).count(),
                "revenue": revenue,
                "recent_requests": ProductRequest.objects.filter(seller=profile).select_related(
                    "product", "customer", "customer__profile"
                )[:5],
                "recent_items": paid_items.select_related("order")[:5],
                "attention": products.filter(
                    status__in=[Product.Status.PENDING, Product.Status.REJECTED]
                )[:5],
            }
        )
    return render(request, "dashboards/seller.html", context)


# ----------------------------------------------------------------- admin ----
@admin_required
def admin_dashboard(request):
    paid = Order.objects.filter(status=Order.Status.PAID)
    context = {
        "user_count": User.objects.count(),
        "customer_count": User.objects.filter(role=Role.CUSTOMER).count(),
        "seller_count": SellerProfile.objects.count(),
        "pending_sellers": SellerProfile.objects.filter(status=SellerStatus.PENDING).count(),
        "pending_products": Product.objects.filter(status=Product.Status.PENDING).count(),
        "open_reports": Report.objects.filter(status__in=[Report.Status.OPEN, Report.Status.REVIEWING]).count(),
        "order_count": Order.objects.count(),
        "revenue": paid.aggregate(total=Sum("total_amount"))["total"] or Decimal("0.00"),
        "recent_sellers": SellerProfile.objects.filter(status=SellerStatus.PENDING).select_related("user")[:5],
        "recent_products": Product.objects.filter(status=Product.Status.PENDING).select_related("seller")[:5],
        "recent_orders": Order.objects.select_related("customer")[:5],
    }
    return render(request, "dashboards/admin.html", context)


# ----------------------------------------------------------------- users ----
@admin_required
def manage_users(request):
    users = User.objects.select_related("profile")
    term = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    if term:
        users = users.filter(
            Q(username__icontains=term) | Q(email__icontains=term) | Q(profile__full_name__icontains=term)
        )
    if role in Role.values:
        users = users.filter(role=role)
    return render(
        request,
        "dashboards/manage_users.html",
        {"page_obj": _page(request, users), "q": term, "role": role, "roles": Role.choices},
    )


@admin_required
@require_POST
def user_toggle_active(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, _("You cannot deactivate your own account."))
    elif target.is_superuser and not request.user.is_superuser:
        messages.error(request, _("Only a superuser can change a superuser account."))
    else:
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        audit_logger.info(
            "Admin %s set user %s active=%s", request.user.pk, target.pk, target.is_active
        )
        messages.success(
            request,
            _("Account activated.") if target.is_active else _("Account deactivated."),
        )
    return redirect(safe_next_url(request, "dashboard:users"))


# --------------------------------------------------------------- sellers ----
@admin_required
def manage_sellers(request):
    sellers = SellerProfile.objects.select_related("user")
    status = request.GET.get("status", "")
    term = request.GET.get("q", "").strip()
    if status in SellerStatus.values:
        sellers = sellers.filter(status=status)
    if term:
        sellers = sellers.filter(Q(shop_name__icontains=term) | Q(user__email__icontains=term))
    sellers = sellers.annotate(product_total=Count("products"))
    return render(
        request,
        "dashboards/manage_sellers.html",
        {"page_obj": _page(request, sellers), "status": status, "q": term, "statuses": SellerStatus.choices},
    )


@admin_required
@require_POST
def seller_set_status(request, pk):
    seller = get_object_or_404(SellerProfile.objects.select_related("user"), pk=pk)
    form = SellerStatusForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Invalid status."))
        return redirect("dashboard:sellers")
    seller.status = form.cleaned_data["status"]
    seller.status_note = form.cleaned_data["note"]
    seller.save(update_fields=["status", "status_note", "updated_at"])
    audit_logger.info("Admin %s set seller %s status=%s", request.user.pk, seller.pk, seller.status)
    notify(
        seller.user,
        _("Your shop status is now: %(status)s.") % {"status": seller.get_status_display()},
        reverse("dashboard:seller"),
    )
    messages.success(request, _("Seller status updated."))
    return redirect(safe_next_url(request, "dashboard:sellers"))


# -------------------------------------------------------------- products ----
@admin_required
def manage_products(request):
    products = Product.objects.select_related("seller", "category")
    status = request.GET.get("status", "")
    term = request.GET.get("q", "").strip()
    if status in Product.Status.values:
        products = products.filter(status=status)
    if term:
        products = products.filter(Q(name__icontains=term) | Q(seller__shop_name__icontains=term))
    return render(
        request,
        "dashboards/manage_products.html",
        {"page_obj": _page(request, products), "status": status, "q": term, "statuses": Product.Status.choices},
    )


@admin_required
@require_POST
def product_moderate(request, pk):
    product = get_object_or_404(Product.objects.select_related("seller__user"), pk=pk)
    form = ProductModerationForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("dashboard:products")
    action = form.cleaned_data["action"]
    if action == "publish":
        product.status, product.rejection_reason = Product.Status.PUBLISHED, ""
    elif action == "reject":
        product.status, product.rejection_reason = Product.Status.REJECTED, form.cleaned_data["reason"]
    else:
        product.status = Product.Status.PENDING
    product.save(update_fields=["status", "rejection_reason", "updated_at"])
    audit_logger.info("Admin %s moderated product %s: %s", request.user.pk, product.pk, action)
    notify(
        product.seller.user,
        _("Your listing \"%(name)s\" is now: %(status)s.")
        % {"name": product.name, "status": product.get_status_display()},
        reverse("products:edit", kwargs={"slug": product.slug}),
    )
    messages.success(request, _("Listing updated."))
    return redirect(safe_next_url(request, "dashboard:products"))


# ------------------------------------------------------------ categories ----
@admin_required
def manage_categories(request):
    form = CategoryForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        category = form.save()
        audit_logger.info("Admin %s created category %s", request.user.pk, category.pk)
        messages.success(request, _("Category created."))
        return redirect("dashboard:categories")
    categories = Category.objects.annotate(product_total=Count("products"))
    return render(request, "dashboards/manage_categories.html", {"form": form, "categories": categories})


@admin_required
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, request.FILES or None, instance=category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Category updated."))
        return redirect("dashboard:categories")
    return render(request, "dashboards/category_form.html", {"form": form, "category": category})


@admin_required
@require_POST
def category_toggle(request, pk):
    category = get_object_or_404(Category, pk=pk)
    category.is_active = not category.is_active
    category.save(update_fields=["is_active"])
    messages.success(
        request, _("Category activated.") if category.is_active else _("Category hidden from the marketplace.")
    )
    return redirect("dashboard:categories")


# ------------------------------------------------------ requests / orders ----
@admin_required
def manage_requests(request):
    queryset = ProductRequest.objects.select_related("product", "customer", "seller")
    status = request.GET.get("status", "")
    if status in ProductRequest.Status.values:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "dashboards/manage_requests.html",
        {"page_obj": _page(request, queryset), "status": status, "statuses": ProductRequest.Status.choices},
    )


@admin_required
def manage_orders(request):
    queryset = Order.objects.select_related("customer").annotate(item_total=Count("items"))
    status = request.GET.get("status", "")
    term = request.GET.get("q", "").strip()
    if status in Order.Status.values:
        queryset = queryset.filter(status=status)
    if term:
        queryset = queryset.filter(Q(reference__icontains=term) | Q(customer__username__icontains=term))
    return render(
        request,
        "dashboards/manage_orders.html",
        {"page_obj": _page(request, queryset), "status": status, "q": term, "statuses": Order.Status.choices},
    )


@admin_required
def order_detail(request, pk):
    order = get_object_or_404(
        Order.objects.select_related("customer").prefetch_related("items", "payments"), pk=pk
    )
    return render(request, "dashboards/order_detail.html", {"order": order})


# --------------------------------------------------- reports / reviews ----
@admin_required
def manage_reports(request):
    queryset = Report.objects.select_related("product", "reporter")
    status = request.GET.get("status", "")
    if status in Report.Status.values:
        queryset = queryset.filter(status=status)
    page = _page(request, queryset, 10)
    for report in page:
        report.update_form = ReportUpdateForm(instance=report, prefix=f"r{report.pk}")
    return render(
        request,
        "dashboards/manage_reports.html",
        {"page_obj": page, "status": status, "statuses": Report.Status.choices},
    )


@admin_required
@require_POST
def report_update(request, pk):
    report = get_object_or_404(Report, pk=pk)
    form = ReportUpdateForm(request.POST, instance=report, prefix=f"r{report.pk}")
    if form.is_valid():
        form.save()
        audit_logger.info("Admin %s updated report %s -> %s", request.user.pk, report.pk, report.status)
        messages.success(request, _("Report updated."))
    else:
        messages.error(request, _("Could not update the report."))
    return redirect("dashboard:reports")


@admin_required
def manage_reviews(request):
    queryset = Review.objects.select_related("product", "customer")
    visibility = request.GET.get("visibility", "")
    if visibility == "hidden":
        queryset = queryset.filter(is_visible=False)
    elif visibility == "visible":
        queryset = queryset.filter(is_visible=True)
    return render(
        request,
        "dashboards/manage_reviews.html",
        {"page_obj": _page(request, queryset), "visibility": visibility},
    )


@admin_required
@require_POST
def review_toggle(request, pk):
    review = get_object_or_404(Review, pk=pk)
    review.is_visible = not review.is_visible
    review.save(update_fields=["is_visible"])
    audit_logger.info("Admin %s set review %s visible=%s", request.user.pk, review.pk, review.is_visible)
    messages.success(request, _("Review is now visible.") if review.is_visible else _("Review hidden."))
    return redirect("dashboard:reviews")


# ------------------------------------------------------------ statistics ----
@admin_required
def statistics(request):
    now = timezone.now()
    since = now - timedelta(days=30)
    paid = Order.objects.filter(status=Order.Status.PAID)
    line_value = ExpressionWrapper(
        F("unit_price") * F("quantity"), output_field=DecimalField(max_digits=16, decimal_places=2)
    )
    context = {
        "totals": {
            "users": User.objects.count(),
            "sellers": SellerProfile.objects.filter(status=SellerStatus.APPROVED).count(),
            "products": Product.objects.filter(status=Product.Status.PUBLISHED).count(),
            "orders": Order.objects.count(),
            "paid_orders": paid.count(),
            "revenue": paid.aggregate(t=Sum("total_amount"))["t"] or Decimal("0.00"),
            "requests": ProductRequest.objects.count(),
            "reviews": Review.objects.count(),
        },
        "last_30": {
            "new_users": User.objects.filter(date_joined__gte=since).count(),
            "orders": Order.objects.filter(created_at__gte=since).count(),
            "revenue": paid.filter(created_at__gte=since).aggregate(t=Sum("total_amount"))["t"]
            or Decimal("0.00"),
        },
        "top_sellers": (
            OrderItem.objects.filter(order__status=Order.Status.PAID, seller__isnull=False)
            .values("seller__shop_name")
            .annotate(revenue=Sum(line_value), units=Sum("quantity"))
            .order_by("-revenue")[:5]
        ),
        "top_categories": (
            Category.objects.annotate(
                product_total=Count("products", filter=Q(products__status=Product.Status.PUBLISHED))
            )
            .filter(product_total__gt=0)
            .order_by("-product_total")[:5]
        ),
        "order_status": Order.objects.values("status").annotate(n=Count("id")).order_by("status"),
        "payment_status": Payment.objects.values("status").annotate(n=Count("id")).order_by("status"),
    }
    return render(request, "dashboards/statistics.html", context)
