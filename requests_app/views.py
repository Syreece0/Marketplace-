from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.permissions import approved_seller_required, customer_required
from notifications.services import notify
from products.models import Product

from .forms import ProductRequestForm, SellerResponseForm
from .models import ProductRequest


def _paginate(request, queryset, per_page=10):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


# ------------------------------------------------------------ customer ----
@customer_required
def request_create(request, slug):
    product = get_object_or_404(
        Product.objects.public().select_related("seller", "seller__user"), slug=slug
    )
    form = ProductRequestForm(request.POST or None, product=product)
    if request.method == "POST":
        if ProductRequest.objects.filter(
            customer=request.user, product=product, status=ProductRequest.Status.PENDING
        ).exists():
            messages.info(request, _("You already have a pending request for this product."))
            return redirect("requests_app:customer_list")
        if form.is_valid():
            product_request = form.save(commit=False)
            product_request.customer = request.user
            product_request.seller = product.seller
            product_request.product = product
            try:
                with transaction.atomic():
                    product_request.full_clean()
                    product_request.save()
            except ValidationError:
                messages.error(request, _("Your request could not be saved."))
            except IntegrityError:
                messages.info(request, _("You already have a pending request for this product."))
                return redirect("requests_app:customer_list")
            else:
                notify(
                    product.seller.user,
                    _("New request from %(name)s for \"%(product)s\".")
                    % {"name": request.user.display_name, "product": product.name},
                    reverse("requests_app:seller_detail", kwargs={"pk": product_request.pk}),
                )
                messages.success(request, _("Your request has been sent to the seller."))
                return redirect("requests_app:customer_detail", pk=product_request.pk)
    return render(request, "requests/request_form.html", {"form": form, "product": product})


@customer_required
def customer_list(request):
    queryset = ProductRequest.objects.filter(customer=request.user).select_related("product", "seller")
    status = request.GET.get("status", "")
    if status in ProductRequest.Status.values:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "requests/customer_list.html",
        {"page_obj": _paginate(request, queryset), "status": status, "statuses": ProductRequest.Status.choices},
    )


@customer_required
def customer_detail(request, pk):
    product_request = get_object_or_404(
        ProductRequest.objects.select_related("product", "seller"), pk=pk, customer=request.user
    )
    return render(request, "requests/customer_detail.html", {"req": product_request})


@customer_required
@require_POST
def customer_cancel(request, pk):
    product_request = get_object_or_404(ProductRequest, pk=pk, customer=request.user)
    try:
        product_request.transition_to(ProductRequest.Status.CANCELLED)
    except ValidationError:
        messages.error(request, _("This request can no longer be cancelled."))
    else:
        notify(
            product_request.seller.user,
            _("A request for \"%(product)s\" was cancelled by the customer.")
            % {"product": product_request.product.name},
            reverse("requests_app:seller_detail", kwargs={"pk": product_request.pk}),
        )
        messages.success(request, _("Your request has been cancelled."))
    return redirect("requests_app:customer_detail", pk=product_request.pk)


# -------------------------------------------------------------- seller ----
@approved_seller_required
def seller_list(request):
    queryset = ProductRequest.objects.filter(seller=request.user.seller_profile).select_related(
        "product", "customer", "customer__profile"
    )
    status = request.GET.get("status", "")
    if status in ProductRequest.Status.values:
        queryset = queryset.filter(status=status)
    return render(
        request,
        "requests/seller_list.html",
        {"page_obj": _paginate(request, queryset), "status": status, "statuses": ProductRequest.Status.choices},
    )


@approved_seller_required
def seller_detail(request, pk):
    product_request = get_object_or_404(
        ProductRequest.objects.select_related("product", "customer", "customer__profile"),
        pk=pk,
        seller=request.user.seller_profile,
    )
    return render(
        request,
        "requests/seller_detail.html",
        {"req": product_request, "form": SellerResponseForm()},
    )


@approved_seller_required
@require_POST
def seller_respond(request, pk):
    product_request = get_object_or_404(
        ProductRequest.objects.select_related("product", "customer"),
        pk=pk,
        seller=request.user.seller_profile,
    )
    form = SellerResponseForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Invalid action."))
        return redirect("requests_app:seller_detail", pk=pk)
    new_status = SellerResponseForm.ACTIONS[form.cleaned_data["action"]]
    try:
        product_request.transition_to(new_status, form.cleaned_data["response"])
    except ValidationError:
        messages.error(request, _("That status change is not allowed for this request."))
    else:
        notify(
            product_request.customer,
            _("Your request for \"%(product)s\" is now: %(status)s.")
            % {"product": product_request.product.name, "status": product_request.get_status_display()},
            reverse("requests_app:customer_detail", kwargs={"pk": product_request.pk}),
        )
        messages.success(request, _("The request has been updated."))
    return redirect("requests_app:seller_detail", pk=pk)
