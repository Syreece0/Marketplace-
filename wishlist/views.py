from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.permissions import customer_required
from core.utils import is_ajax, safe_next_url
from products.models import Product

from .models import WishlistItem


@customer_required
def wishlist_list(request):
    items = (
        WishlistItem.objects.filter(user=request.user)
        .select_related("product", "product__seller__user", "product__category")
    )
    page = Paginator(items, 12).get_page(request.GET.get("page"))
    return render(request, "wishlist/wishlist.html", {"page_obj": page})


@customer_required
@require_POST
def toggle(request, product_id):
    """Save or un-save a product. Returns JSON for AJAX calls, else redirects."""
    product = get_object_or_404(Product.objects.public(), pk=product_id)
    item, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
    if not created:
        item.delete()
    saved = created
    message = _("Product saved to your wishlist.") if saved else _("Product removed from your wishlist.")
    if is_ajax(request):
        return JsonResponse(
            {
                "saved": saved,
                "message": message,
                "count": WishlistItem.objects.filter(user=request.user).count(),
            }
        )
    messages.success(request, message)
    return redirect(safe_next_url(request, product.get_absolute_url()))


@customer_required
@require_POST
def remove(request, pk):
    item = get_object_or_404(WishlistItem, pk=pk, user=request.user)
    item.delete()
    messages.success(request, _("Product removed from your wishlist."))
    return redirect("wishlist:list")
