from django.urls import reverse

from core.factories import BaseTestCase, make_customer, make_product, make_seller
from notifications.models import Notification
from requests_app.models import ProductRequest


class ProductRequestTests(BaseTestCase):
    def setUp(self):
        self.seller_user, self.shop = make_seller("seller1")
        self.product = make_product(self.shop, quantity=5)
        self.customer = make_customer("cust1")

    def create_url(self):
        return reverse("requests_app:create", args=[self.product.slug])

    def test_customer_can_submit_valid_request(self):
        self.login(self.customer)
        response = self.client.post(self.create_url(), {"quantity": 2, "message": "Is it new?"})
        req = ProductRequest.objects.get()
        self.assertRedirects(response, reverse("requests_app:customer_detail", args=[req.pk]))
        self.assertEqual(req.customer, self.customer)
        self.assertEqual(req.seller, self.shop)
        self.assertEqual(req.status, ProductRequest.Status.PENDING)
        self.assertTrue(Notification.objects.filter(user=self.seller_user).exists())

    def test_invalid_quantities_rejected(self):
        self.login(self.customer)
        for bad in ("0", "-1", "6", "abc", ""):
            self.client.post(self.create_url(), {"quantity": bad, "message": "x"})
        self.assertEqual(ProductRequest.objects.count(), 0)

    def test_seller_and_status_cannot_be_forged(self):
        other_user, other_shop = make_seller("seller2")
        self.login(self.customer)
        self.client.post(
            self.create_url(),
            {"quantity": 1, "message": "hi", "seller": other_shop.pk, "status": "accepted"},
        )
        req = ProductRequest.objects.get()
        self.assertEqual(req.seller, self.shop)
        self.assertEqual(req.status, ProductRequest.Status.PENDING)

    def test_duplicate_pending_request_blocked(self):
        self.login(self.customer)
        self.client.post(self.create_url(), {"quantity": 1})
        self.client.post(self.create_url(), {"quantity": 1})
        self.assertEqual(ProductRequest.objects.count(), 1)

    def test_cannot_request_unpublished_product(self):
        hidden = make_product(self.shop, name="Hidden", status="pending")
        self.login(self.customer)
        response = self.client.post(reverse("requests_app:create", args=[hidden.slug]), {"quantity": 1})
        self.assertEqual(response.status_code, 404)

    def test_anonymous_and_sellers_cannot_create_requests(self):
        self.assertEqual(self.client.post(self.create_url(), {"quantity": 1}).status_code, 302)
        self.login(self.seller_user)
        self.assertEqual(self.client.post(self.create_url(), {"quantity": 1}).status_code, 403)
        self.assertEqual(ProductRequest.objects.count(), 0)

    def test_model_validates_seller_matches_product(self):
        from django.core.exceptions import ValidationError
        _, other_shop = make_seller("seller3")
        req = ProductRequest(customer=self.customer, seller=other_shop, product=self.product, quantity=1)
        with self.assertRaises(ValidationError):
            req.full_clean()


class SellerHandlingTests(BaseTestCase):
    def setUp(self):
        self.seller_user, self.shop = make_seller("seller1")
        self.rival_user, self.rival_shop = make_seller("rival")
        self.customer = make_customer("cust1")
        self.other_customer = make_customer("cust2")
        self.product = make_product(self.shop)
        self.req = ProductRequest.objects.create(
            customer=self.customer, seller=self.shop, product=self.product, quantity=1, message="Hello"
        )

    def respond(self, action, response="Ok"):
        return self.client.post(
            reverse("requests_app:seller_respond", args=[self.req.pk]), {"action": action, "response": response}
        )

    def test_seller_can_accept_then_complete(self):
        self.login(self.seller_user)
        self.respond("accept", "Yes, available")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.ACCEPTED)
        self.assertEqual(self.req.seller_response, "Yes, available")
        self.assertTrue(Notification.objects.filter(user=self.customer).exists())
        self.respond("complete", "")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.COMPLETED)

    def test_seller_can_reject(self):
        self.login(self.seller_user)
        self.respond("reject", "Sorry")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.REJECTED)

    def test_invalid_transitions_are_refused(self):
        self.login(self.seller_user)
        self.respond("complete")  # pending -> completed is not allowed
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.PENDING)
        self.respond("reject")
        self.respond("accept")  # rejected -> accepted is not allowed
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.REJECTED)

    def test_unknown_action_is_refused(self):
        self.login(self.seller_user)
        self.respond("delete-everything")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.PENDING)

    def test_other_seller_cannot_view_or_modify(self):
        self.login(self.rival_user)
        self.assertEqual(self.client.get(reverse("requests_app:seller_detail", args=[self.req.pk])).status_code, 404)
        self.assertEqual(self.respond("accept").status_code, 404)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.PENDING)
        listing = self.client.get(reverse("requests_app:seller_list"))
        self.assertEqual(len(listing.context["page_obj"]), 0)

    def test_customers_cannot_use_seller_endpoints(self):
        self.login(self.customer)
        self.assertEqual(self.respond("accept").status_code, 403)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.PENDING)

    def test_customer_can_cancel_own_pending_request(self):
        self.login(self.customer)
        response = self.client.post(reverse("requests_app:customer_cancel", args=[self.req.pk]))
        self.assertEqual(response.status_code, 302)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.CANCELLED)
        # A finished request cannot be cancelled again.
        self.client.post(reverse("requests_app:customer_cancel", args=[self.req.pk]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.CANCELLED)

    def test_other_customer_cannot_see_or_cancel_request(self):
        self.login(self.other_customer)
        self.assertEqual(self.client.get(reverse("requests_app:customer_detail", args=[self.req.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("requests_app:customer_cancel", args=[self.req.pk])).status_code, 404)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ProductRequest.Status.PENDING)

    def test_customer_list_only_shows_own_requests(self):
        ProductRequest.objects.create(customer=self.other_customer, seller=self.shop, product=self.product, quantity=1)
        self.login(self.customer)
        page = self.client.get(reverse("requests_app:customer_list"))
        self.assertEqual(len(page.context["page_obj"]), 1)

    def test_customer_cannot_use_respond_endpoint_via_get(self):
        self.login(self.seller_user)
        response = self.client.get(reverse("requests_app:seller_respond", args=[self.req.pk]))
        self.assertEqual(response.status_code, 405)
