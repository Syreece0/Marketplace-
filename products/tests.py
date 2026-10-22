from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import SellerStatus
from core.factories import (
    BaseTestCase, image_upload, make_admin, make_category, make_customer, make_product, make_seller,
)
from orders.models import Order, OrderItem
from products.models import Product, Report, Review


class ProductCreationTests(BaseTestCase):
    def setUp(self):
        self.user, self.shop = make_seller()
        self.category = make_category()
        self.login(self.user)

    def payload(self, **overrides):
        data = {
            "name": "Blue Lamp", "category": self.category.pk, "description": "A nice lamp.",
            "price": "2500.00", "quantity": "4", "condition": "new",
        }
        data.update(overrides)
        return data

    def test_valid_listing_is_saved_as_pending_and_not_public(self):
        response = self.client.post(reverse("products:create"), self.payload())
        product = Product.objects.get(name="Blue Lamp")
        self.assertRedirects(response, reverse("products:edit", args=[product.slug]))
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.seller, self.shop)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("products:list")), "Blue Lamp")
        self.assertEqual(self.client.get(product.get_absolute_url()).status_code, 404)

    def test_seller_cannot_set_status_or_owner_through_form(self):
        other_user, other_shop = make_seller("other")
        self.client.post(
            reverse("products:create"),
            self.payload(status="published", seller=other_shop.pk, rejection_reason="x"),
        )
        product = Product.objects.get(name="Blue Lamp")
        self.assertEqual(product.status, Product.Status.PENDING)
        self.assertEqual(product.seller, self.shop)

    def test_invalid_prices_rejected(self):
        for bad in ("0", "-5", "abc", ""):
            response = self.client.post(reverse("products:create"), self.payload(price=bad))
            self.assertEqual(response.status_code, 200, bad)
        self.assertFalse(Product.objects.exists())

    def test_negative_quantity_rejected(self):
        response = self.client.post(reverse("products:create"), self.payload(quantity="-1"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.exists())

    def test_inactive_category_rejected(self):
        hidden = make_category("Hidden", is_active=False)
        response = self.client.post(reverse("products:create"), self.payload(category=hidden.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.exists())

    def test_valid_image_accepted(self):
        data = self.payload(image=image_upload())
        self.client.post(reverse("products:create"), data)
        product = Product.objects.get(name="Blue Lamp")
        self.assertTrue(product.image)

    def test_fake_image_rejected(self):
        fake = SimpleUploadedFile("evil.png", b"<?php echo 1; ?>", content_type="image/png")
        response = self.client.post(reverse("products:create"), self.payload(image=fake))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valid image")
        self.assertFalse(Product.objects.exists())

    def test_wrong_extension_rejected(self):
        upload = image_upload(name="photo.gif", fmt="GIF")
        response = self.client.post(reverse("products:create"), self.payload(image=upload))
        self.assertContains(response, "Unsupported image type")

    def test_oversized_image_rejected(self):
        with self.settings(MAX_IMAGE_UPLOAD_MB=0):
            response = self.client.post(reverse("products:create"), self.payload(image=image_upload()))
        self.assertContains(response, "too large")
        self.assertFalse(Product.objects.exists())

    def test_gallery_image_upload_and_limit(self):
        product = make_product(self.shop, self.category)
        url = reverse("products:image_add", args=[product.slug])
        self.client.post(url, {"image": image_upload("a.png"), "alt_text": "front"})
        self.assertEqual(product.images.count(), 1)
        with self.settings(MAX_GALLERY_IMAGES=1):
            self.client.post(url, {"image": image_upload("b.png")})
        self.assertEqual(product.images.count(), 1)


class OwnershipTests(BaseTestCase):
    def setUp(self):
        self.owner, self.owner_shop = make_seller("owner")
        self.rival, self.rival_shop = make_seller("rival")
        self.product = make_product(self.owner_shop)

    def test_other_seller_cannot_edit_delete_or_toggle(self):
        self.login(self.rival)
        edit = reverse("products:edit", args=[self.product.slug])
        self.assertEqual(self.client.get(edit).status_code, 404)
        self.assertEqual(self.client.post(edit, {"name": "Hacked"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("products:delete", args=[self.product.slug])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("products:toggle_availability", args=[self.product.slug])).status_code, 404
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Test product")

    def test_other_seller_cannot_delete_gallery_image(self):
        from products.models import ProductImage
        image = ProductImage.objects.create(product=self.product, image=image_upload())
        self.login(self.rival)
        response = self.client.post(reverse("products:image_delete", args=[image.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ProductImage.objects.filter(pk=image.pk).exists())

    def test_customer_cannot_edit_products(self):
        self.login(make_customer())
        self.assertEqual(self.client.get(reverse("products:edit", args=[self.product.slug])).status_code, 403)

    def test_owner_can_edit_and_delete(self):
        self.login(self.owner)
        category = self.product.category
        response = self.client.post(
            reverse("products:edit", args=[self.product.slug]),
            {"name": "Test product", "category": category.pk, "description": "A product used in tests.",
             "price": "1200.00", "quantity": "7", "condition": "used"},
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.price, Decimal("1200.00"))
        # Price/stock changes keep a published listing published...
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)
        response = self.client.post(reverse("products:delete", args=[self.product.slug]))
        self.assertRedirects(response, reverse("products:seller_list"))
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())

    def test_changing_description_sends_listing_back_for_approval(self):
        self.login(self.owner)
        self.client.post(
            reverse("products:edit", args=[self.product.slug]),
            {"name": "Test product", "category": self.product.category.pk, "description": "Completely new text",
             "price": "1000.00", "quantity": "10", "condition": "new"},
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING)

    def test_delete_requires_post(self):
        self.login(self.owner)
        response = self.client.get(reverse("products:delete", args=[self.product.slug]))
        self.assertEqual(response.status_code, 405)

    def test_owner_can_preview_unpublished_listing_but_public_cannot(self):
        pending = make_product(self.owner_shop, name="Draft thing", status=Product.Status.PENDING)
        self.assertEqual(self.client.get(pending.get_absolute_url()).status_code, 404)
        self.login(make_customer())
        self.assertEqual(self.client.get(pending.get_absolute_url()).status_code, 404)
        self.client.logout()
        self.login(self.owner)
        response = self.client.get(pending.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preview only")


class PublicVisibilityTests(BaseTestCase):
    def setUp(self):
        self.user, self.shop = make_seller()
        self.category = make_category()

    def test_only_published_products_from_approved_shops_are_listed(self):
        make_product(self.shop, self.category, name="Visible one")
        make_product(self.shop, self.category, name="Pending one", status=Product.Status.PENDING)
        make_product(self.shop, self.category, name="Rejected one", status=Product.Status.REJECTED)
        _, suspended_shop = make_seller("sus", status=SellerStatus.SUSPENDED)
        make_product(suspended_shop, self.category, name="Suspended shop item")
        hidden_category = make_category("Hidden cat", is_active=False)
        make_product(self.shop, hidden_category, name="Hidden category item")

        page = self.client.get(reverse("products:list"))
        self.assertContains(page, "Visible one")
        for name in ("Pending one", "Rejected one", "Suspended shop item", "Hidden category item"):
            self.assertNotContains(page, name)
        home = self.client.get(reverse("core:home"))
        self.assertContains(home, "Visible one")
        self.assertNotContains(home, "Pending one")

    def test_suspended_seller_shop_page_is_404(self):
        _, suspended_shop = make_seller("sus2", status=SellerStatus.SUSPENDED)
        self.assertEqual(self.client.get(reverse("products:shop", args=[suspended_shop.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("products:shop", args=[self.shop.slug])).status_code, 200)

    def test_shop_page_lists_only_public_products(self):
        make_product(self.shop, self.category, name="Shop visible")
        make_product(self.shop, self.category, name="Shop pending", status=Product.Status.PENDING)
        page = self.client.get(reverse("products:shop", args=[self.shop.slug]))
        self.assertContains(page, "Shop visible")
        self.assertNotContains(page, "Shop pending")

    def test_product_detail_has_title_and_description_meta(self):
        product = make_product(self.shop, self.category, name="Meta Test Item")
        page = self.client.get(product.get_absolute_url())
        self.assertContains(page, "<title>Meta Test Item")
        self.assertContains(page, 'name="description"')


class SearchFilterPaginationTests(BaseTestCase):
    def setUp(self):
        _, self.shop = make_seller()
        self.cat_a = make_category("Alpha")
        self.cat_b = make_category("Beta")
        for i in range(15):
            make_product(self.shop, self.cat_a, name=f"Widget {i:02d}", price=Decimal(100 + i))
        make_product(self.shop, self.cat_b, name="Gizmo special", price=Decimal("5000"), condition="used")
        make_product(self.shop, self.cat_b, name="Sold out thing", quantity=0)

    def test_pagination(self):
        first = self.client.get(reverse("products:list"))
        self.assertEqual(len(first.context["page_obj"]), 12)
        self.assertEqual(first.context["page_obj"].paginator.count, 17)
        second = self.client.get(reverse("products:list"), {"page": 2})
        self.assertEqual(len(second.context["page_obj"]), 5)

    def test_invalid_page_number_does_not_crash(self):
        self.assertEqual(self.client.get(reverse("products:list"), {"page": "abc"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("products:list"), {"page": 999}).status_code, 200)

    def test_search(self):
        page = self.client.get(reverse("products:list"), {"q": "gizmo"})
        self.assertEqual([p.name for p in page.context["page_obj"]], ["Gizmo special"])

    def test_filters(self):
        by_category = self.client.get(reverse("products:list"), {"category": self.cat_b.pk})
        self.assertEqual(by_category.context["page_obj"].paginator.count, 2)
        by_condition = self.client.get(reverse("products:list"), {"condition": "used"})
        self.assertEqual([p.name for p in by_condition.context["page_obj"]], ["Gizmo special"])
        by_price = self.client.get(reverse("products:list"), {"min_price": "4000", "max_price": "6000"})
        self.assertEqual([p.name for p in by_price.context["page_obj"]], ["Gizmo special"])
        in_stock = self.client.get(reverse("products:list"), {"in_stock": "on", "category": self.cat_b.pk})
        self.assertEqual([p.name for p in in_stock.context["page_obj"]], ["Gizmo special"])

    def test_sorting(self):
        asc = self.client.get(reverse("products:list"), {"sort": "price_asc"})
        self.assertEqual(asc.context["page_obj"][0].name, "Widget 00")
        desc = self.client.get(reverse("products:list"), {"sort": "price_desc"})
        self.assertEqual(desc.context["page_obj"][0].name, "Gizmo special")

    def test_garbage_filters_are_ignored(self):
        page = self.client.get(reverse("products:list"), {"min_price": "abc", "category": "9999", "sort": "evil"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["page_obj"].paginator.count, 17)

    def test_category_page(self):
        page = self.client.get(self.cat_a.get_absolute_url())
        self.assertEqual(page.context["page_obj"].paginator.count, 15)
        hidden = make_category("Secret", is_active=False)
        self.assertEqual(self.client.get(hidden.get_absolute_url()).status_code, 404)

    def test_pagination_links_keep_search_terms(self):
        page = self.client.get(reverse("products:list"), {"q": "Widget"})
        self.assertContains(page, "q=Widget&amp;page=2")

    def test_empty_state(self):
        page = self.client.get(reverse("products:list"), {"q": "zzzzzz"})
        self.assertContains(page, "No products found")


class DownloadTests(BaseTestCase):
    def setUp(self):
        self.user, self.shop = make_seller()
        self.product = make_product(self.shop, image=image_upload())

    def test_downloads_require_login(self):
        for name in ("products:download_pdf", "products:download_image"):
            response = self.client.get(reverse(name, args=[self.product.slug]))
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/login/", response.url)

    def test_customer_can_download_pdf_and_image(self):
        self.login(make_customer())
        pdf = self.client.get(reverse("products:download_pdf", args=[self.product.slug]))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertIn("attachment", pdf["Content-Disposition"])
        image = self.client.get(reverse("products:download_image", args=[self.product.slug]))
        self.assertEqual(image.status_code, 200)
        self.assertIn("attachment", image["Content-Disposition"])
        b"".join(image.streaming_content)  # close the file handle

    def test_unpublished_product_downloads_are_denied_to_strangers_but_allowed_to_owner(self):
        pending = make_product(self.shop, name="Secret draft", status=Product.Status.PENDING, image=image_upload())
        self.login(make_customer())
        self.assertEqual(self.client.get(reverse("products:download_pdf", args=[pending.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("products:download_image", args=[pending.slug])).status_code, 404)
        self.client.logout()
        self.login(self.user)
        self.assertEqual(self.client.get(reverse("products:download_pdf", args=[pending.slug])).status_code, 200)

    def test_missing_image_returns_404(self):
        no_image = make_product(self.shop, name="No picture")
        self.login(make_customer())
        self.assertEqual(self.client.get(reverse("products:download_image", args=[no_image.slug])).status_code, 404)

    def test_pdf_handles_special_characters(self):
        tricky = make_product(self.shop, name="Tom & Jerry <b>Box</b>", description="Line1\nLine2 & <script>")
        self.login(make_customer())
        response = self.client.get(reverse("products:download_pdf", args=[tricky.slug]))
        self.assertEqual(response.status_code, 200)


class ReviewAndReportTests(BaseTestCase):
    def setUp(self):
        self.user, self.shop = make_seller()
        self.product = make_product(self.shop)
        self.buyer = make_customer("buyer")

    def _buy(self, status=Order.Status.PAID):
        order = Order.objects.create(
            customer=self.buyer, status=status, total_amount=Decimal("1000"), shipping_name="B",
            shipping_phone="1", shipping_address="A", shipping_city="C",
        )
        OrderItem.objects.create(
            order=order, product=self.product, seller=self.shop, product_name=self.product.name,
            seller_name=self.shop.shop_name, unit_price=Decimal("1000"), quantity=1,
        )
        return order

    def test_only_paid_buyers_can_review_and_only_once(self):
        self.login(self.buyer)
        url = reverse("products:review", args=[self.product.slug])
        self.client.post(url, {"rating": 5, "comment": "Great"})
        self.assertEqual(Review.objects.count(), 0)  # never bought

        self._buy(status=Order.Status.PENDING_PAYMENT)
        self.client.post(url, {"rating": 5, "comment": "Great"})
        self.assertEqual(Review.objects.count(), 0)  # unpaid order does not count

        self._buy()
        self.client.post(url, {"rating": 4, "comment": "Good"})
        self.assertEqual(Review.objects.count(), 1)
        self.client.post(url, {"rating": 1, "comment": "Changed my mind"})
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().rating, 4)

    def test_invalid_rating_rejected(self):
        self._buy()
        self.login(self.buyer)
        url = reverse("products:review", args=[self.product.slug])
        for bad in ("0", "6", "x", ""):
            self.client.post(url, {"rating": bad, "comment": "?"})
        self.assertEqual(Review.objects.count(), 0)

    def test_hidden_reviews_are_not_shown(self):
        self._buy()
        Review.objects.create(product=self.product, customer=self.buyer, rating=5, comment="Visible praise")
        self.assertContains(self.client.get(self.product.get_absolute_url()), "Visible praise")
        Review.objects.update(is_visible=False)
        self.assertNotContains(self.client.get(self.product.get_absolute_url()), "Visible praise")

    def test_customer_can_report_listing(self):
        self.login(self.buyer)
        admin = make_admin()
        response = self.client.post(
            reverse("products:report", args=[self.product.slug]), {"reason": "suspicious", "details": "Looks fake"}
        )
        self.assertRedirects(response, self.product.get_absolute_url())
        report = Report.objects.get()
        self.assertEqual(report.reporter, self.buyer)
        self.assertEqual(report.status, Report.Status.OPEN)
        self.assertTrue(admin.notifications.exists())

    def test_anonymous_and_seller_cannot_report(self):
        url = reverse("products:report", args=[self.product.slug])
        self.assertEqual(self.client.post(url, {"reason": "other"}).status_code, 302)
        self.login(self.user)
        self.assertEqual(self.client.post(url, {"reason": "other"}).status_code, 403)
        self.assertEqual(Report.objects.count(), 0)

    def test_invalid_report_reason_rejected(self):
        self.login(self.buyer)
        self.client.post(reverse("products:report", args=[self.product.slug]), {"reason": "nonsense"})
        self.assertEqual(Report.objects.count(), 0)


class ModelConstraintTests(BaseTestCase):
    def test_database_rejects_non_positive_price(self):
        from django.db import IntegrityError, transaction
        _, shop = make_seller()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_product(shop, price=Decimal("0"))

    def test_slugs_are_unique(self):
        _, shop = make_seller()
        a = make_product(shop, name="Same name")
        b = make_product(shop, name="Same name")
        self.assertNotEqual(a.slug, b.slug)
