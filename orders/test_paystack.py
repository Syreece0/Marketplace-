"""Tests for the 10% commission, seller payouts and the Paystack payment flow.

Paystack itself is never contacted: ``orders.paystack._call`` is replaced by a fake.
"""
import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from core.factories import BaseTestCase, make_admin, make_customer, make_product, make_seller
from notifications.models import Notification
from orders import paystack, services
from orders.models import Order, Payment

SHIPPING = {
    "shipping_name": "Ada Buyer", "shipping_phone": "08000000000",
    "shipping_address": "1 Marina Road", "shipping_city": "Lagos", "notes": "",
}
SECRET = "sk_test_unit_tests"
LIVE = override_settings(PAYMENT_GATEWAY="paystack", PAYMENT_SECRET_KEY=SECRET)


class FakePaystack:
    """Stands in for orders.paystack._call and records every request."""

    def __init__(self):
        self.calls = []
        self.verify_data = {}
        self.fail_paths = set()

    def __call__(self, method, path, payload=None, timeout=20):
        self.calls.append((method, path, payload))
        for bad in self.fail_paths:
            if path.startswith(bad):
                raise paystack.PaystackError("Provider said no.")
        if path.startswith("/bank/resolve"):
            return {"account_name": "ADA OKAFOR"}
        if path.startswith("/bank"):
            return [{"code": "058", "name": "GTBank"}, {"code": "044", "name": "Access Bank"}]
        if path == "/subaccount":
            return {"subaccount_code": "ACCT_new"}
        if path.startswith("/subaccount/"):
            return {}
        if path == "/transaction/initialize":
            return {"authorization_url": "https://checkout.paystack.com/abc123"}
        if path.startswith("/transaction/verify/"):
            return self.verify_data
        raise AssertionError(f"unexpected Paystack call {method} {path}")

    def payload_for(self, path):
        return next(p for _m, pth, p in self.calls if pth == path)


def sign(body):
    return hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()


class CommissionMathTests(BaseTestCase):
    def test_ten_percent_split_rounds_to_kobo(self):
        self.assertEqual(services.split_commission(Decimal("3001.00")), (Decimal("300.10"), Decimal("2700.90")))
        self.assertEqual(services.split_commission(Decimal("333.33")), (Decimal("33.33"), Decimal("300.00")))
        commission, earnings = services.split_commission(Decimal("0.05"))
        self.assertEqual(commission + earnings, Decimal("0.05"))

    @override_settings(COMMISSION_PERCENT=Decimal("7.5"))
    def test_rate_is_configurable(self):
        self.assertEqual(services.split_commission(Decimal("1000")), (Decimal("75.00"), Decimal("925.00")))

    def test_to_kobo(self):
        self.assertEqual(paystack.to_kobo(Decimal("1500.50")), 150050)
        self.assertEqual(paystack.to_kobo(Decimal("0.01")), 1)

    def test_order_items_store_commission_at_purchase_time(self):
        _, shop = make_seller()
        product = make_product(shop, price=Decimal("1500.50"), quantity=5)
        customer = make_customer()
        services.add_to_cart(customer, product, 2)
        order = services.create_order(customer, SHIPPING)
        item = order.items.get()
        self.assertEqual(item.commission_rate, Decimal("10.00"))
        self.assertEqual(item.commission_amount, Decimal("300.10"))
        self.assertEqual(item.seller_earnings, Decimal("2700.90"))
        with override_settings(COMMISSION_PERCENT=Decimal("20")):
            item.refresh_from_db()
            self.assertEqual(item.commission_amount, Decimal("300.10"))  # old orders never change


class SignatureTests(BaseTestCase):
    @LIVE
    def test_signature_check(self):
        body = b'{"event":"charge.success"}'
        self.assertTrue(paystack.valid_signature(body, sign(body)))
        self.assertFalse(paystack.valid_signature(body, "0" * 128))
        self.assertFalse(paystack.valid_signature(body, ""))
        self.assertFalse(paystack.valid_signature(b"tampered", sign(body)))


@LIVE
class PayoutAccountTests(BaseTestCase):
    def setUp(self):
        cache.clear()
        self.fake = FakePaystack()
        patcher = mock.patch("orders.paystack._call", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user, self.shop = make_seller()
        self.login(self.user)

    def test_page_lists_banks(self):
        page = self.client.get(reverse("accounts:payout_settings"))
        self.assertContains(page, "GTBank")
        self.assertContains(page, "cannot buy your products until")

    def test_verified_account_creates_subaccount(self):
        response = self.client.post(
            reverse("accounts:payout_settings"), {"bank": "058", "account_number": "0123456789"}
        )
        self.assertRedirects(response, reverse("accounts:payout_settings"))
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.paystack_subaccount_code, "ACCT_new")
        self.assertEqual(self.shop.account_name, "ADA OKAFOR")
        self.assertEqual(self.shop.bank_name, "GTBank")
        self.assertEqual(self.shop.masked_account_number, "******6789")
        created = self.fake.payload_for("/subaccount")
        self.assertEqual(created["settlement_bank"], "058")
        self.assertEqual(created["account_number"], "0123456789")

    def test_second_save_updates_the_same_subaccount(self):
        self.shop.paystack_subaccount_code = "ACCT_old"
        self.shop.save()
        self.client.post(reverse("accounts:payout_settings"), {"bank": "044", "account_number": "0123456789"})
        self.assertIn(("PUT", "/subaccount/ACCT_old"), [(m, p) for m, p, _ in self.fake.calls])
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.paystack_subaccount_code, "ACCT_old")

    def test_bad_account_number_rejected_before_calling_paystack(self):
        for bad in ("123", "abcdefghij", "01234567890"):
            page = self.client.post(reverse("accounts:payout_settings"), {"bank": "058", "account_number": bad})
            self.assertEqual(page.status_code, 200)
        self.assertFalse([c for c in self.fake.calls if c[1].startswith("/bank/resolve")])

    def test_unverifiable_account_is_not_saved(self):
        self.fake.fail_paths.add("/bank/resolve")
        page = self.client.post(reverse("accounts:payout_settings"), {"bank": "058", "account_number": "0123456789"})
        self.assertContains(page, "Provider said no.")
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.paystack_subaccount_code, "")

    def test_unknown_bank_rejected(self):
        page = self.client.post(reverse("accounts:payout_settings"), {"bank": "999", "account_number": "0123456789"})
        self.assertEqual(page.status_code, 200)
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.account_number, "")

    def test_only_sellers_can_open_the_page(self):
        self.client.logout()
        self.login(make_customer())
        self.assertEqual(self.client.get(reverse("accounts:payout_settings")).status_code, 403)

    @override_settings(PAYMENT_GATEWAY="test")
    def test_page_explains_when_in_test_mode(self):
        self.assertContains(self.client.get(reverse("accounts:payout_settings")), "test-payment mode")


@LIVE
class OnlinePaymentTests(BaseTestCase):
    def setUp(self):
        cache.clear()
        self.fake = FakePaystack()
        patcher = mock.patch("orders.paystack._call", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.seller_user, self.shop = make_seller()
        self.shop.paystack_subaccount_code = "ACCT_shop1"
        self.shop.save()
        self.product = make_product(self.shop, price=Decimal("1500.50"), quantity=5)
        self.customer = self.login(make_customer())
        services.add_to_cart(self.customer, self.product, 2)  # 3001.00 total
        self.order = services.create_order(self.customer, SHIPPING)

    def start(self):
        return self.client.post(reverse("orders:pay", args=[self.order.pk]))

    def reference(self):
        return self.order.payments.get(status=Payment.Status.PENDING).reference

    def succeed(self, reference, amount="3001.00"):
        self.fake.verify_data = {
            "status": "success", "amount": paystack.to_kobo(Decimal(amount)),
            "currency": "NGN", "reference": reference,
        }

    # ---- starting a payment
    def test_pay_redirects_to_paystack_with_a_ninety_ten_split(self):
        response = self.start()
        self.assertRedirects(response, "https://checkout.paystack.com/abc123", fetch_redirect_response=False)
        payload = self.fake.payload_for("/transaction/initialize")
        self.assertEqual(payload["amount"], 300100)
        self.assertEqual(payload["email"], self.customer.email)
        self.assertEqual(payload["currency"], "NGN")
        self.assertTrue(payload["callback_url"].endswith(reverse("orders:payment_return")))
        self.assertEqual(payload["split"], {
            "type": "flat",
            "bearer_type": "account",  # the administrator pays Paystack's fee
            "subaccounts": [{"subaccount": "ACCT_shop1", "share": 270090}],  # seller gets 90%
        })
        self.assertEqual(payload["reference"], self.reference())

    def test_every_attempt_gets_a_fresh_reference(self):
        first = self.reference()
        self.start()
        second = self.reference()
        self.assertNotEqual(first, second)
        self.assertEqual(self.order.payments.get(reference=first).status, Payment.Status.CANCELLED)

    def test_split_adds_up_across_two_shops(self):
        _, shop2 = make_seller("seller2")
        shop2.paystack_subaccount_code = "ACCT_shop2"
        shop2.save()
        other = make_product(shop2, name="Other", price=Decimal("5000.00"), quantity=3)
        customer2 = make_customer("buyer2")
        services.add_to_cart(customer2, self.product, 1)
        services.add_to_cart(customer2, other, 1)
        order = services.create_order(customer2, SHIPPING)
        payment = order.payments.get()
        split = services.get_gateway().build_split(order)
        shares = {entry["subaccount"]: entry["share"] for entry in split["subaccounts"]}
        self.assertEqual(shares, {"ACCT_shop1": 135045, "ACCT_shop2": 450000})
        total_kobo = paystack.to_kobo(payment.amount)
        commission_kobo = total_kobo - sum(shares.values())
        self.assertEqual(commission_kobo, 65005)  # exactly 10% of 6500.50

    def test_test_payment_is_not_available_in_live_mode(self):
        with self.assertRaises(services.PaymentError):
            services.pay_order(self.order)
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_provider_outage_leaves_order_unpaid_with_a_friendly_message(self):
        self.fake.fail_paths.add("/transaction/initialize")
        response = self.start()
        # fetch_redirect_response=False so the flash message is still waiting for the next request
        self.assertRedirects(response, reverse("orders:detail", args=[self.order.pk]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("orders:detail", args=[self.order.pk])), "could not start the payment")
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_cannot_pay_someone_elses_order(self):
        self.client.logout()
        self.login(make_customer("intruder"))
        self.assertEqual(self.start().status_code, 404)

    # ---- confirming a payment
    def test_return_page_verifies_and_marks_paid(self):
        self.start()
        reference = self.reference()
        self.succeed(reference)
        response = self.client.get(reverse("orders:payment_return"), {"reference": reference})
        self.assertRedirects(response, reverse("orders:detail", args=[self.order.pk]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertEqual(self.order.payments.get(reference=reference).status, Payment.Status.PAID)
        self.assertTrue(Notification.objects.filter(user=self.seller_user, message__contains="New paid order").exists())

    def test_confirming_twice_does_nothing_new(self):
        self.start()
        reference = self.reference()
        self.succeed(reference)
        for _ in range(3):
            self.client.get(reverse("orders:payment_return"), {"reference": reference})
        self.assertEqual(Notification.objects.filter(user=self.seller_user).count(), 1)
        verify_calls = [c for c in self.fake.calls if c[1].startswith("/transaction/verify/")]
        self.assertEqual(len(verify_calls), 1)  # already paid, so Paystack is not asked again

    def test_wrong_amount_is_never_accepted(self):
        self.start()
        reference = self.reference()
        self.succeed(reference, amount="10.00")
        self.client.get(reverse("orders:payment_return"), {"reference": reference})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING_PAYMENT)

    def test_failed_payment_keeps_order_open_for_another_try(self):
        self.start()
        reference = self.reference()
        self.fake.verify_data = {"status": "failed", "amount": 300100, "currency": "NGN"}
        self.client.get(reverse("orders:payment_return"), {"reference": reference})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(self.order.payments.get(reference=reference).status, Payment.Status.FAILED)
        self.assertRedirects(self.start(), "https://checkout.paystack.com/abc123", fetch_redirect_response=False)

    def test_unfinished_payment_stays_pending(self):
        self.start()
        reference = self.reference()
        self.fake.verify_data = {"status": "abandoned"}
        self.client.get(reverse("orders:payment_return"), {"reference": reference})
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_verification_outage_does_not_mark_paid(self):
        self.start()
        reference = self.reference()
        self.fake.fail_paths.add("/transaction/verify/")
        self.client.get(reverse("orders:payment_return"), {"reference": reference})
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_customer_cannot_confirm_another_customers_payment(self):
        self.start()
        reference = self.reference()
        self.succeed(reference)
        self.client.logout()
        self.login(make_customer("intruder"))
        self.assertEqual(self.client.get(reverse("orders:payment_return"), {"reference": reference}).status_code, 404)
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_return_page_needs_a_known_reference(self):
        self.assertEqual(self.client.get(reverse("orders:payment_return")).status_code, 404)
        self.assertEqual(self.client.get(reverse("orders:payment_return"), {"reference": "nope"}).status_code, 404)

    def test_money_arriving_for_a_cancelled_order_alerts_the_administrator(self):
        admin = make_admin()
        self.start()
        reference = self.reference()
        services.cancel_order(self.order)  # customer cancels while on the Paystack page
        self.succeed(reference)
        services.confirm_online_payment(reference)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.order.payments.get(reference=reference).status, Payment.Status.PAID)
        self.assertTrue(Notification.objects.filter(user=admin, message__contains="Please refund").exists())

    # ---- webhook
    def post_webhook(self, event, reference, signature=None):
        body = json.dumps({"event": event, "data": {"reference": reference}}).encode()
        return self.client.post(
            reverse("orders:paystack_webhook"), data=body, content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature if signature is not None else sign(body),
        )

    def test_webhook_marks_order_paid_without_the_customer_returning(self):
        self.start()
        reference = self.reference()
        self.succeed(reference)
        self.client.logout()
        self.assertEqual(self.post_webhook("charge.success", reference).status_code, 200)
        self.assertEqual(Order.objects.get().status, Order.Status.PAID)

    def test_webhook_with_bad_signature_is_rejected(self):
        self.start()
        reference = self.reference()
        self.succeed(reference)
        self.assertEqual(self.post_webhook("charge.success", reference, signature="bad").status_code, 400)
        self.assertEqual(self.post_webhook("charge.success", reference, signature="").status_code, 400)
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_webhook_does_not_trust_the_message_alone(self):
        self.start()
        reference = self.reference()
        self.fake.verify_data = {"status": "failed"}  # Paystack says it did not succeed
        self.post_webhook("charge.success", reference)
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_webhook_ignores_other_events_and_unknown_references(self):
        self.assertEqual(self.post_webhook("transfer.success", "x").status_code, 200)
        self.assertEqual(self.post_webhook("charge.success", "PAY-DOESNOTEXIST").status_code, 200)

    def test_webhook_asks_paystack_to_retry_when_verification_is_down(self):
        self.start()
        reference = self.reference()
        self.fake.fail_paths.add("/transaction/verify/")
        self.assertEqual(self.post_webhook("charge.success", reference).status_code, 503)

    def test_webhook_only_accepts_post(self):
        self.assertEqual(self.client.get(reverse("orders:paystack_webhook")).status_code, 405)

    # ---- seller readiness
    def test_products_of_shops_without_payout_account_cannot_be_added(self):
        _, bare = make_seller("bare")
        item = make_product(bare, name="Bare item")
        with self.assertRaises(services.CartError):
            services.add_to_cart(self.customer, item, 1)

    def test_checkout_blocked_if_shop_lost_its_payout_account(self):
        services.add_to_cart(self.customer, self.product, 1)
        self.shop.paystack_subaccount_code = ""
        self.shop.save()
        with self.assertRaises(services.CheckoutError):
            services.create_order(self.customer, SHIPPING)

    @override_settings(PAYSTACK_MAX_SELLERS_PER_ORDER=1)
    def test_order_with_too_many_shops_is_refused(self):
        _, shop2 = make_seller("seller2")
        shop2.paystack_subaccount_code = "ACCT_shop2"
        shop2.save()
        other = make_product(shop2, name="Other")
        services.add_to_cart(self.customer, self.product, 1)
        services.add_to_cart(self.customer, other, 1)
        with self.assertRaises(services.CheckoutError):
            services.create_order(self.customer, SHIPPING)

    # ---- refunds
    def test_admin_records_refund(self):
        self.start()
        reference = self.reference()
        self.succeed(reference)
        services.confirm_online_payment(reference)
        services.record_refund(self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.REFUNDED)
        self.assertEqual(self.order.payments.get(reference=reference).status, Payment.Status.REFUNDED)
        self.assertEqual(self.order.items.get().fulfillment_status, "cancelled")
        self.assertTrue(Notification.objects.filter(user=self.customer, message__contains="refunded").exists())
        self.assertTrue(Notification.objects.filter(user=self.seller_user, message__contains="refunded").exists())

    def test_unpaid_order_cannot_be_marked_refunded(self):
        with self.assertRaises(services.PaymentError):
            services.record_refund(self.order)

    def test_refunded_orders_leave_the_seller_queue(self):
        self.start()
        reference = self.reference()
        self.succeed(reference)
        services.confirm_online_payment(reference)
        services.record_refund(self.order)
        self.client.logout()
        self.login(self.seller_user)
        page = self.client.get(reverse("orders:seller_list"))
        self.assertEqual(len(page.context["page_obj"].object_list), 0)


class EarningsDisplayTests(BaseTestCase):
    def test_seller_and_admin_dashboards_show_earnings_and_commission(self):
        seller_user, shop = make_seller()
        product = make_product(shop, price=Decimal("1000.00"), quantity=5)
        customer = make_customer()
        services.add_to_cart(customer, product, 2)
        order = services.create_order(customer, SHIPPING)
        services.pay_order(order)

        self.login(seller_user)
        self.assertEqual(self.client.get(reverse("dashboard:seller")).context["earnings"], Decimal("1800.00"))
        orders_page = self.client.get(reverse("orders:seller_list"))
        self.assertContains(orders_page, "₦1,800.00")
        self.assertContains(orders_page, "₦200.00 commission")

        self.client.logout()
        self.login(make_admin())
        self.assertEqual(self.client.get(reverse("dashboard:admin")).context["commission"], Decimal("200.00"))

    def test_customers_do_not_see_commission_details(self):
        _, shop = make_seller()
        product = make_product(shop, price=Decimal("1000.00"))
        customer = self.login(make_customer())
        services.add_to_cart(customer, product, 1)
        order = services.create_order(customer, SHIPPING)
        page = self.client.get(reverse("orders:detail", args=[order.pk]))
        self.assertNotContains(page, "commission")
