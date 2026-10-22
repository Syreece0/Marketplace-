import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts.models import SellerProfile, SellerStatus
from core.permissions import approved_seller_required, customer_required
from core.utils import audit_logger
from notifications.services import notify, notify_admins
from orders.forms import QuantityForm
from orders.models import Order, OrderItem
from requests_app.forms import ProductRequestForm
from wishlist.services import wishlisted_ids

from .forms import (
    ProductFilterForm,
    ProductForm,
    ProductImageForm,
    ReportForm,
    ReviewForm,
)
from .models import Category, Product, ProductImage, Review
from .pdf import build_product_pdf

SORTING = {
    "newest": "-created_at",
    "price_asc": "price",
    "price_desc": "-price",
    "name": "name",
}


# ------------------------------------------------------------- browsing ----
def _apply_filters(queryset, form, ignore_category=False):
    form.is_valid()  # populates cleaned_data with the valid fields only
    data = getattr(form, "cleaned_data", {})
    query = data.get("q")
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
            | Q(seller__shop_name__icontains=query)
        )
    if data.get("category") and not ignore_category:
        queryset = queryset.filter(category=data["category"])
    if data.get("condition"):
        queryset = queryset.filter(condition=data["condition"])
    if data.get("min_price") is not None:
        queryset = queryset.filter(price__gte=data["min_price"])
    if data.get("max_price") is not None:
        queryset = queryset.filter(price__lte=data["max_price"])
    if data.get("in_stock"):
        queryset = queryset.filter(availability=Product.Availability.AVAILABLE, quantity__gt=0)
    return queryset.order_by(SORTING.get(data.get("sort") or "newest", "-created_at"), "-id")


def marketplace(request, slug=None):
    category = None
    queryset = Product.objects.public().select_related("seller", "category")
    if slug:
        category = get_object_or_404(Category, slug=slug, is_active=True)
        queryset = queryset.filter(category=category)
    form = ProductFilterForm(request.GET)
    queryset = _apply_filters(queryset, form, ignore_category=category is not None)
    page = Paginator(queryset, settings.PRODUCTS_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "products/marketplace.html",
        {
            "page_obj": page,
            "form": form,
            "category": category,
            "categories": Category.objects.filter(is_active=True),
            "wishlisted_ids": wishlisted_ids(request.user),
        },
    )


def _can_preview(user, product):
    if not user.is_authenticated:
        return False
    if user.is_marketplace_admin:
        return True
    return user.is_seller and product.seller.user_id == user.pk


def _get_viewable_product(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("seller", "seller__user", "category"), slug=slug
    )
    if not product.is_public and not _can_preview(request.user, product):
        raise Http404
    return product


def _purchase_for_review(user, product):
    return (
        OrderItem.objects.filter(
            order__customer=user, order__status=Order.Status.PAID, product=product
        )
        .select_related("order")
        .order_by("-order__created_at")
        .first()
    )


def product_detail(request, slug):
    product = _get_viewable_product(request, slug)
    user = request.user
    reviews = product.reviews.filter(is_visible=True).select_related("customer", "customer__profile")
    summary = reviews.aggregate(average=Avg("rating"), count=Count("id"))
    related = (
        Product.objects.public()
        .filter(category=product.category)
        .exclude(pk=product.pk)
        .select_related("seller", "category")[:4]
    )

    can_review = False
    if user.is_authenticated and user.is_customer:
        already = Review.objects.filter(product=product, customer=user).exists()
        can_review = not already and _purchase_for_review(user, product) is not None

    return render(
        request,
        "products/detail.html",
        {
            "product": product,
            "gallery": product.images.all(),
            "reviews": reviews[:20],
            "review_summary": summary,
            "related": related,
            "wishlisted_ids": wishlisted_ids(user),
            "request_form": ProductRequestForm(initial={"quantity": 1}),
            "quantity_form": QuantityForm(initial={"quantity": 1}),
            "can_review": can_review,
            "review_form": ReviewForm(),
            "report_form": ReportForm(),
            "is_preview": not product.is_public,
        },
    )


def seller_shop(request, slug):
    shop = get_object_or_404(
        SellerProfile, slug=slug, status=SellerStatus.APPROVED, user__is_active=True
    )
    queryset = Product.objects.public().filter(seller=shop).select_related("seller", "category")
    page = Paginator(queryset, settings.PRODUCTS_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "products/shop.html",
        {"shop": shop, "page_obj": page, "wishlisted_ids": wishlisted_ids(request.user)},
    )


# ---------------------------------------------------- seller management ----
def _own_product(request, slug):
    return get_object_or_404(Product, slug=slug, seller=request.user.seller_profile)


@approved_seller_required
def seller_product_list(request):
    queryset = Product.objects.filter(seller=request.user.seller_profile).select_related("category")
    status = request.GET.get("status", "")
    if status in Product.Status.values:
        queryset = queryset.filter(status=status)
    term = request.GET.get("q", "").strip()
    if term:
        queryset = queryset.filter(name__icontains=term)
    page = Paginator(queryset, 12).get_page(request.GET.get("page"))
    return render(
        request,
        "products/seller_list.html",
        {"page_obj": page, "status": status, "q": term, "statuses": Product.Status.choices},
    )


@approved_seller_required
def product_create(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.seller = request.user.seller_profile
        product.status = Product.Status.PENDING
        product.save()
        audit_logger.info("Product created: id=%s seller_id=%s", product.pk, product.seller_id)
        notify_admins(
            _("New listing awaiting approval: %(name)s") % {"name": product.name},
            "/manage/products/?status=pending",
        )
        messages.success(
            request, _("Your product was saved and is waiting for administrator approval.")
        )
        return redirect("products:edit", slug=product.slug)
    return render(request, "products/product_form.html", {"form": form, "product": None})


@approved_seller_required
def product_edit(request, slug):
    product = _own_product(request, slug)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    image_form = ProductImageForm(product=product)
    if request.method == "POST" and form.is_valid():
        # Changing what customers see on a live (or rejected) listing sends it
        # back for approval; stock and price updates do not.
        needs_review = (
            product.status in (Product.Status.PUBLISHED, Product.Status.REJECTED)
            and {"name", "description", "image", "category"} & set(form.changed_data)
        )
        product = form.save(commit=False)
        if needs_review:
            product.status = Product.Status.PENDING
            product.rejection_reason = ""
        product.save()
        if needs_review:
            notify_admins(
                _("Listing updated and awaiting approval: %(name)s") % {"name": product.name},
                "/manage/products/?status=pending",
            )
            messages.warning(
                request, _("Your changes were saved. The listing needs approval again before it is public.")
            )
        else:
            messages.success(request, _("Your product has been updated."))
        return redirect("products:edit", slug=product.slug)
    return render(
        request,
        "products/product_form.html",
        {"form": form, "product": product, "image_form": image_form, "gallery": product.images.all()},
    )


@approved_seller_required
@require_POST
def product_delete(request, slug):
    product = _own_product(request, slug)
    name = product.name
    product.delete()
    audit_logger.info("Product deleted: name=%s seller_id=%s", name, request.user.seller_profile.pk)
    messages.success(request, _("\"%(name)s\" was deleted.") % {"name": name})
    return redirect("products:seller_list")


@approved_seller_required
@require_POST
def product_toggle_availability(request, slug):
    product = _own_product(request, slug)
    if product.availability == Product.Availability.AVAILABLE:
        product.availability = Product.Availability.UNAVAILABLE
        message = _("The product is now marked as unavailable.")
    else:
        product.availability = Product.Availability.AVAILABLE
        message = _("The product is now marked as available.")
    product.save(update_fields=["availability", "updated_at"])
    messages.success(request, message)
    return redirect("products:seller_list")


@approved_seller_required
@require_POST
def product_image_add(request, slug):
    product = _own_product(request, slug)
    form = ProductImageForm(request.POST, request.FILES, product=product)
    if form.is_valid():
        image = form.save(commit=False)
        image.product = product
        image.position = product.images.count()
        image.save()
        messages.success(request, _("Image added."))
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect("products:edit", slug=product.slug)


@approved_seller_required
@require_POST
def product_image_delete(request, pk):
    image = get_object_or_404(ProductImage, pk=pk, product__seller=request.user.seller_profile)
    slug = image.product.slug
    image.delete()
    messages.success(request, _("Image removed."))
    return redirect("products:edit", slug=slug)


# ----------------------------------------------------------- downloads ----
@login_required
def download_image(request, slug, image_id=None):
    product = _get_viewable_product(request, slug)
    if image_id is not None:
        field = get_object_or_404(ProductImage, pk=image_id, product=product).image
    else:
        field = product.image
    if not field:
        raise Http404
    try:
        handle = field.open("rb")
    except FileNotFoundError:
        raise Http404
    extension = os.path.splitext(field.name)[1].lower()
    suffix = f"-{image_id}" if image_id is not None else ""
    return FileResponse(handle, as_attachment=True, filename=f"{product.slug}{suffix}{extension}")


@login_required
def download_pdf(request, slug):
    product = _get_viewable_product(request, slug)
    response = HttpResponse(build_product_pdf(product), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{product.slug}-info.pdf"'
    return response


# ------------------------------------------------- reviews and reports ----
@customer_required
@require_POST
def review_create(request, slug):
    product = get_object_or_404(Product.objects.public(), slug=slug)
    purchase = _purchase_for_review(request.user, product)
    if purchase is None:
        messages.error(request, _("You can only review products you have bought."))
        return redirect(product)
    if Review.objects.filter(product=product, customer=request.user).exists():
        messages.error(request, _("You have already reviewed this product."))
        return redirect(product)
    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.product = product
        review.customer = request.user
        review.order = purchase.order
        try:
            review.save()
        except IntegrityError:
            messages.error(request, _("You have already reviewed this product."))
        else:
            notify(
                product.seller.user,
                _("New %(n)s-star review on \"%(name)s\".") % {"n": review.rating, "name": product.name},
                product.get_absolute_url(),
            )
            messages.success(request, _("Thank you for your review."))
    else:
        messages.error(request, _("Please choose a rating from 1 to 5."))
    return redirect(product)


@customer_required
@require_POST
def report_create(request, slug):
    product = get_object_or_404(Product.objects.public(), slug=slug)
    form = ReportForm(request.POST)
    if form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.product = product
        report.save()
        audit_logger.info("Report #%s filed on product_id=%s", report.pk, product.pk)
        notify_admins(
            _("New report on listing: %(name)s") % {"name": product.name}, "/manage/reports/"
        )
        messages.success(request, _("Thank you. Our team will review your report."))
    else:
        messages.error(request, _("Please choose a reason for your report."))
    return redirect(product)
