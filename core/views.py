"""Public pages and error handlers."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from products.models import Category, Product

from .forms import ContactForm


def home(request):
    products = (
        Product.objects.public()
        .select_related("seller", "category")
        .order_by("-created_at")[:8]
    )
    categories = Category.objects.filter(is_active=True).order_by("name")[:8]
    from wishlist.services import wishlisted_ids

    return render(
        request,
        "core/home.html",
        {
            "products": products,
            "categories": categories,
            "wishlisted_ids": wishlisted_ids(request.user),
        },
    )


def about(request):
    return render(request, "core/about.html")


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.send()
        messages.success(request, _("Thank you. Your message has been sent."))
        return redirect("core:contact")
    return render(request, "core/contact.html", {"form": form})


def terms(request):
    return render(request, "core/terms.html")


def privacy(request):
    return render(request, "core/privacy.html")


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)
