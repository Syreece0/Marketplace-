from decimal import Decimal

from django.urls import reverse

from accounts.models import SellerStatus, User
from core.factories import (
    BaseTestCase, make_admin, make_category, make_customer, make_product, make_seller,
)
from notifications.models import Notification
from orders.models import Order, OrderItem
from products.models import Category, Product, Report, Review


class AdminSellerApprovalTests(BaseTestCase):
    def setUp(self):
        self.admin = self.login(make_admin())
        self.seller_user, self.shop = make_seller("newshop", status=SellerStatus.PENDING)

    def set_status(self, status, note=""):
        return self.client.post(
            reverse("dashboard:seller_status", args=[self.shop.pk]), {"status": status, "note": note}
        )

    def test_admin_approves_and_seller_is_notified(self):
        self.set_status("approved")
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, SellerStatus.APPROVED)
        self.assertTrue(self.seller_user.notifications.filter(message__contains="Approved").exists())
        self.client.logout()
        self.login(self.seller_user)
        self.assertEqual(self.client.get(reverse("products:create")).status_code, 200)

    def test_rejection_note_is_visible_to_seller(self):
        self.set_status("rejected", "Missing business details")
        self.client.logout()
        self.login(self.seller_user)
        page = self.client.get(reverse("dashboard:seller"))
        self.assertContains(page, "Missing business details")
        self.assertEqual(self.client.get(reverse("products:create")).status_code, 302)

    def test_suspension_hides_existing_products(self):
        self.set_status("approved")
        category = make_category()
        product = make_product(self.shop, category)
        self.assertContains(self.client.get(reverse("products:list")), product.name)
        self.set_status("suspended")
        self.assertNotContains(self.client.get(reverse("products:list")), product.name)

    def test_invalid_status_rejected(self):
        self.set_status("super-approved")
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, SellerStatus.PENDING)

    def test_non_admins_cannot_change_status(self):
        self.client.logout()
        self.login(self.seller_user)
        self.assertEqual(self.set_status("approved").status_code, 403)
        self.client.logout()
        self.login(make_customer())
        self.assertEqual(self.set_status("approved").status_code, 403)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.status, SellerStatus.PENDING)

    def test_seller_list_filters(self):
        page = self.client.get(reverse("dashboard:sellers"), {"status": "pending"})
        self.assertEqual(len(page.context["page_obj"]), 1)
        page = self.client.get(reverse("dashboard:sellers"), {"status": "approved"})
        self.assertEqual(len(page.context["page_obj"]), 0)


class AdminProductModerationTests(BaseTestCase):
    def setUp(self):
        self.admin = self.login(make_admin())
        self.seller_user, self.shop = make_seller()
        self.product = make_product(self.shop, status=Product.Status.PENDING)

    def moderate(self, action, reason=""):
        return self.client.post(
            reverse("dashboard:product_moderate", args=[self.product.pk]), {"action": action, "reason": reason}
        )

    def test_publish_makes_listing_public(self):
        self.moderate("publish")
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PUBLISHED)
        self.client.logout()
        self.assertEqual(self.client.get(self.product.get_absolute_url()).status_code, 200)

    def test_reject_requires_reason_and_stores_it(self):
        self.moderate("reject")
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING)
        self.moderate("reject", "Blurry photos")
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.REJECTED)
        self.assertEqual(self.product.rejection_reason, "Blurry photos")
        self.assertTrue(Notification.objects.filter(user=self.seller_user).exists())

    def test_non_admin_cannot_moderate(self):
        self.client.logout()
        self.login(self.seller_user)
        self.assertEqual(self.moderate("publish").status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING)

    def test_unknown_action_ignored(self):
        self.moderate("explode")
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.PENDING)

    def test_open_redirect_is_blocked(self):
        response = self.client.post(
            reverse("dashboard:product_moderate", args=[self.product.pk]),
            {"action": "publish", "next": "https://evil.example/"},
        )
        self.assertNotIn("evil.example", response.url)


class AdminUserManagementTests(BaseTestCase):
    def setUp(self):
        self.admin = self.login(make_admin())
        self.customer = make_customer("target")

    def toggle(self, user):
        return self.client.post(reverse("dashboard:user_toggle_active", args=[user.pk]))

    def test_deactivate_and_reactivate(self):
        self.toggle(self.customer)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.client.logout()
        self.assertFalse(self.client.login(username="target", password="Str0ng-Test-Pass!42"))
        self.login(self.admin)
        self.toggle(self.customer)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_admin_cannot_deactivate_self(self):
        self.toggle(self.admin)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_non_superuser_admin_cannot_touch_superuser(self):
        root = User.objects.create_superuser("root", "root@example.com", "Str0ng-Test-Pass!42")
        self.toggle(root)
        root.refresh_from_db()
        self.assertTrue(root.is_active)

    def test_customers_cannot_toggle_accounts(self):
        self.client.logout()
        self.login(self.customer)
        victim = make_customer("victim")
        self.assertEqual(self.toggle(victim).status_code, 403)

    def test_user_search_and_role_filter(self):
        make_seller("someseller")
        page = self.client.get(reverse("dashboard:users"), {"q": "target"})
        self.assertEqual([u.username for u in page.context["page_obj"]], ["target"])
        page = self.client.get(reverse("dashboard:users"), {"role": "seller"})
        self.assertEqual([u.username for u in page.context["page_obj"]], ["someseller"])


class AdminCategoryTests(BaseTestCase):
    def setUp(self):
        self.admin = self.login(make_admin())

    def test_create_edit_and_hide_category(self):
        self.client.post(reverse("dashboard:categories"), {"name": "Books", "description": "Reading", "is_active": "on"})
        category = Category.objects.get(name="Books")
        self.assertEqual(category.slug, "books")
        self.client.post(reverse("dashboard:category_edit", args=[category.pk]), {"name": "Books & Media", "is_active": "on"})
        category.refresh_from_db()
        self.assertEqual(category.name, "Books & Media")
        self.client.post(reverse("dashboard:category_toggle", args=[category.pk]))
        category.refresh_from_db()
        self.assertFalse(category.is_active)

    def test_duplicate_category_name_rejected(self):
        make_category("Books")
        response = self.client.post(reverse("dashboard:categories"), {"name": "Books", "is_active": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Category.objects.filter(name="Books").count(), 1)

    def test_non_admin_cannot_manage_categories(self):
        self.client.logout()
        self.login(make_customer())
        self.assertEqual(self.client.post(reverse("dashboard:categories"), {"name": "X"}).status_code, 403)
        self.assertFalse(Category.objects.exists())


class AdminReportAndReviewTests(BaseTestCase):
    def setUp(self):
        self.admin = self.login(make_admin())
        _, self.shop = make_seller()
        self.product = make_product(self.shop)
        self.customer = make_customer()

    def test_report_status_update(self):
        report = Report.objects.create(reporter=self.customer, product=self.product, reason="other")
        page = self.client.get(reverse("dashboard:reports"))
        self.assertEqual(page.status_code, 200)
        self.client.post(
            reverse("dashboard:report_update", args=[report.pk]),
            {f"r{report.pk}-status": "resolved", f"r{report.pk}-admin_notes": "Removed the listing"},
        )
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.RESOLVED)
        self.assertEqual(report.admin_notes, "Removed the listing")

    def test_review_moderation(self):
        review = Review.objects.create(product=self.product, customer=self.customer, rating=1, comment="rude text")
        self.client.post(reverse("dashboard:review_toggle", args=[review.pk]))
        review.refresh_from_db()
        self.assertFalse(review.is_visible)
        self.client.post(reverse("dashboard:review_toggle", args=[review.pk]))
        review.refresh_from_db()
        self.assertTrue(review.is_visible)

    def test_customers_cannot_moderate(self):
        review = Review.objects.create(product=self.product, customer=self.customer, rating=5)
        self.client.logout()
        self.login(self.customer)
        self.assertEqual(self.client.post(reverse("dashboard:review_toggle", args=[review.pk])).status_code, 403)


class DashboardContentTests(BaseTestCase):
    def test_admin_dashboard_numbers_come_from_real_data(self):
        admin = self.login(make_admin())
        _, shop = make_seller("shopx", status=SellerStatus.PENDING)
        make_product(shop, status=Product.Status.PENDING)
        page = self.client.get(reverse("dashboard:admin"))
        self.assertEqual(page.context["pending_sellers"], 1)
        self.assertEqual(page.context["pending_products"], 1)
        self.assertEqual(page.context["revenue"], Decimal("0.00"))

    def test_statistics_and_revenue_only_count_paid_orders(self):
        self.login(make_admin())
        seller_user, shop = make_seller()
        product = make_product(shop)
        buyer = make_customer("buyer")
        for status in (Order.Status.PAID, Order.Status.PENDING_PAYMENT, Order.Status.CANCELLED):
            order = Order.objects.create(
                customer=buyer, status=status, total_amount=Decimal("100"), shipping_name="B",
                shipping_phone="1", shipping_address="x", shipping_city="y",
            )
            OrderItem.objects.create(
                order=order, product=product, seller=shop, product_name="Test product",
                seller_name=shop.shop_name, unit_price=Decimal("100"), quantity=1,
            )
        page = self.client.get(reverse("dashboard:statistics"))
        self.assertEqual(page.context["totals"]["revenue"], Decimal("100.00"))
        self.assertEqual(page.context["totals"]["paid_orders"], 1)
        self.assertEqual(list(page.context["top_sellers"])[0]["revenue"], Decimal("100.00"))

    def test_seller_dashboard_shows_own_figures_only(self):
        user, shop = make_seller("mine")
        other_user, other_shop = make_seller("theirs")
        make_product(shop, name="Mine")
        make_product(other_shop, name="Theirs")
        self.login(user)
        page = self.client.get(reverse("dashboard:seller"))
        self.assertEqual(page.context["product_counts"]["total"], 1)

    def test_customer_dashboard_loads_with_empty_states(self):
        self.login(make_customer())
        page = self.client.get(reverse("dashboard:customer"))
        self.assertContains(page, "You have not placed any orders yet.")

    def test_admin_order_detail_and_listing(self):
        self.login(make_admin())
        buyer = make_customer("buyer")
        order = Order.objects.create(
            customer=buyer, total_amount=Decimal("5"), shipping_name="B", shipping_phone="1",
            shipping_address="x", shipping_city="y",
        )
        self.assertEqual(self.client.get(reverse("dashboard:order_detail", args=[order.pk])).status_code, 200)
        page = self.client.get(reverse("dashboard:orders"), {"q": order.reference})
        self.assertEqual(len(page.context["page_obj"]), 1)
