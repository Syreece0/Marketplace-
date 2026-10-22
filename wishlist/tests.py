from django.db import IntegrityError, transaction
from django.urls import reverse

from core.factories import BaseTestCase, make_customer, make_product, make_seller
from wishlist.models import WishlistItem


class WishlistTests(BaseTestCase):
    def setUp(self):
        self.seller_user, self.shop = make_seller()
        self.product = make_product(self.shop)
        self.customer = make_customer("fan")

    def toggle(self, product=None, ajax=False):
        product = product or self.product
        extra = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
        return self.client.post(reverse("wishlist:toggle", args=[product.pk]), **extra)

    def test_customer_can_save_and_remove(self):
        self.login(self.customer)
        self.toggle()
        self.assertEqual(WishlistItem.objects.filter(user=self.customer).count(), 1)
        self.toggle()
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_ajax_toggle_returns_json(self):
        self.login(self.customer)
        saved = self.toggle(ajax=True).json()
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["count"], 1)
        removed = self.toggle(ajax=True).json()
        self.assertFalse(removed["saved"])
        self.assertEqual(removed["count"], 0)

    def test_duplicates_are_prevented_by_database(self):
        WishlistItem.objects.create(user=self.customer, product=self.product)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WishlistItem.objects.create(user=self.customer, product=self.product)

    def test_cannot_save_unpublished_product(self):
        hidden = make_product(self.shop, name="Hidden", status="pending")
        self.login(self.customer)
        self.assertEqual(self.toggle(hidden).status_code, 404)
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_anonymous_and_sellers_cannot_use_wishlist(self):
        self.assertEqual(self.toggle().status_code, 302)
        self.login(self.seller_user)
        self.assertEqual(self.toggle().status_code, 403)
        self.assertEqual(self.client.get(reverse("wishlist:list")).status_code, 403)
        self.assertEqual(WishlistItem.objects.count(), 0)

    def test_toggle_requires_post(self):
        self.login(self.customer)
        self.assertEqual(self.client.get(reverse("wishlist:toggle", args=[self.product.pk])).status_code, 405)

    def test_wishlist_page_shows_only_own_items(self):
        other = make_customer("other")
        other_product = make_product(self.shop, name="Someone elses pick")
        WishlistItem.objects.create(user=other, product=other_product)
        WishlistItem.objects.create(user=self.customer, product=self.product)
        self.login(self.customer)
        page = self.client.get(reverse("wishlist:list"))
        self.assertContains(page, "Test product")
        self.assertNotContains(page, "Someone elses pick")

    def test_cannot_remove_another_customers_item(self):
        other = make_customer("other2")
        item = WishlistItem.objects.create(user=other, product=self.product)
        self.login(self.customer)
        self.assertEqual(self.client.post(reverse("wishlist:remove", args=[item.pk])).status_code, 404)
        self.assertTrue(WishlistItem.objects.filter(pk=item.pk).exists())

    def test_owner_can_remove_item(self):
        item = WishlistItem.objects.create(user=self.customer, product=self.product)
        self.login(self.customer)
        self.client.post(reverse("wishlist:remove", args=[item.pk]))
        self.assertFalse(WishlistItem.objects.filter(pk=item.pk).exists())

    def test_empty_state(self):
        self.login(self.customer)
        self.assertContains(self.client.get(reverse("wishlist:list")), "Your wishlist is empty")

    def test_toggle_ignores_offsite_next_url(self):
        self.login(self.customer)
        response = self.client.post(
            reverse("wishlist:toggle", args=[self.product.pk]), {"next": "https://evil.example/"}
        )
        self.assertEqual(response.url, self.product.get_absolute_url())
