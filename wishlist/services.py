from .models import WishlistItem


def wishlisted_ids(user):
    """IDs of products the user has saved (empty set for anonymous users)."""
    if user is None or not user.is_authenticated:
        return set()
    return set(WishlistItem.objects.filter(user=user).values_list("product_id", flat=True))
