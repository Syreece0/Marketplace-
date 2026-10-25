from decimal import Decimal
from unittest import mock

from django.urls import reverse

from core.factories import BaseTestCase, make_customer, make_product, make_seller
from notifications.models import Notification
from orders import services
from orders.models import Cart, CartItem, Order, OrderItem, Payment
from products.models import Product

SHIPPING = {
    "shipping_name": "Ada Buyer", "shipping_phone": "08000000000",
    "shipping_address": "1 Marina Road", "shipping_city": "Lagos", "notes": "",
}


class CartTests(BaseTestCase):
    def setUp(self):
        self.seller_user, self.shop = make_seller()
        self.product = make_product(self.shop, price=Decimal("250.00"), quantity=5)
        self.customer = self.login(make_customer())

    def add(self, quantity, product=None):
        product = product or self.product
        return self.client.post(reverse("orders:cart_add", args=[product.pk]), {"quantity": quantity})

    def test_add_to_cart_and_merge_quantities(self):
        self.add(2)
        self.add(1)
        item = CartItem.objects.get()
        self.assertEqual(item.quantity, 3)
        self.assertEqual(item.cart.user, self.customer)

    def test_invalid_quantities_rejected(self):
        for bad in ("0", "-2", "abc", "", "1000"):
            self.add(bad)
        self.assertEqual(CartItem.objects.count(), 0)

    def test_cannot_exceed_stock_even_across_several_adds(self):
        self.add(4)
        self.add(2)  # 4 + 2 > 5
        self.assertEqual(CartItem.objects.get().quantity, 4)

    def test_cannot_add_unpublished_or_unavailable_products(self):
        hidden = make_product(self.shop, name="Hidden", status=Product.Status.PENDING)
        self.assertEqual(self.add(1, hidden).status_code, 404)
        paused = make_product(self.shop, name="Paused", availability=Product.Availability.UNAVAILABLE)
        self.add(1, paused)
        out = make_product(self.shop, name="Out", quantity=0)
        self.add(1, out)
        self.assertEqual(CartItem.objects.count(), 0)

    def test_update_and_remove(self):
        self.add(2)
        item = CartItem.objects.get()
        self.client.post(reverse("orders:cart_update", args=[item.pk]), {"quantity": 4})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)
        self.client.post(reverse("orders:cart_update", args=[item.pk]), {"quantity": 50})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)  # over stock: unchanged
        self.client.post(reverse("orders:cart_update", args=[item.pk]), {"quantity": 0})
        self.assertFalse(CartItem.objects.exists())

    def test_cannot_touch_another_customers_cart_item(self):
        other = make_customer("other")
        cart = Cart.objects.create(user=other)
        item = CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        self.assertEqual(self.client.post(reverse("orders:cart_update", args=[item.pk]), {"quantity": 3}).status_code, 404)
        self.assertEqual(self.client.post(reverse("orders:cart_remove", args=[item.pk])).status_code, 404)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)

    def test_cart_page_total_is_server_calculated(self):
        self.add(3)
        page = self.client.get(reverse("orders:cart"))
        self.assertEqual(page.context["total"], Decimal("750.00"))

    def test_empty_cart_state(self):
        self.assertContains(self.client.get(reverse("orders:cart")), "Your cart is empty")
        response = self.client.get(reverse("orders:checkout"))
        self.assertRedirects(response, reverse("orders:cart"))

    def test_database_rejects_zero_quantity(self):
        from django.db import IntegrityError, transaction
        cart = Cart.objects.create(user=self.customer)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CartItem.objects.create(cart=cart, product=self.product, quantity=0)


class CheckoutAndPaymentTests(BaseTestCase):
    def setUp(self):
        self.seller_user, self.shop = make_seller()
        self.p1 = make_product(self.shop, name="Lamp", price=Decimal("1500.50"), quantity=5)
        self.p2 = make_product(self.shop, name="Chair", price=Decimal("20000.00"), quantity=2)
        self.customer = self.login(make_customer())
        self.client.post(reverse("orders:cart_add", args=[self.p1.pk]), {"quantity": 2})
        self.client.post(reverse("orders:cart_add", args=[self.p2.pk]), {"quantity": 1})

    def place_order(self, **overrides):
        data = dict(SHIPPING, **overrides)
        return self.client.post(reverse("orders:checkout"), data)

    def test_order_is_created_with_server_side_prices_and_stock_updated(self):
        response = self.place_order(total_amount="1.00", unit_price="0.01", price="0.01")  # tampering is ignored
        order = Order.objects.get()
        self.assertRedirects(response, reverse("orders:detail", args=[order.pk]))
        self.assertEqual(order.total_amount, Decimal("23001.00"))
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(order.items.count(), 2)
        lamp_line = order.items.get(product_name="Lamp")
        self.assertEqual(lamp_line.unit_price, Decimal("1500.50"))
        self.assertEqual(lamp_line.quantity, 2)
        self.assertEqual(lamp_line.seller_name, self.shop.shop_name)
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual((self.p1.quantity, self.p2.quantity), (3, 1))
        self.assertFalse(CartItem.objects.exists())
        self.assertEqual(order.payments.get().status, Payment.Status.PENDING)
        self.assertEqual(order.payments.get().amount, order.total_amount)

    def test_missing_shipping_fields_rejected_and_values_preserved(self):
        response = self.place_order(shipping_address="", shipping_city="")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)
        self.assertContains(response, "Ada Buyer")
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity, 5)

    def test_price_change_after_order_does_not_change_order(self):
        self.place_order()
        Product.objects.filter(pk=self.p1.pk).update(price=Decimal("1.00"), name="Renamed")
        item = OrderItem.objects.get(product_name="Lamp")
        self.assertEqual(item.unit_price, Decimal("1500.50"))
        self.assertEqual(Order.objects.get().total_amount, Decimal("23001.00"))

    def test_checkout_fails_if_stock_vanished_and_nothing_is_changed(self):
        Product.objects.filter(pk=self.p2.pk).update(quantity=0)
        response = self.place_order()
        self.assertRedirects(response, reverse("orders:cart"), fetch_redirect_response=False)
        self.assertEqual(Order.objects.count(), 0)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity, 5)  # nothing was reserved
        self.assertEqual(CartItem.objects.count(), 2)  # cart kept

    def test_checkout_fails_when_product_is_unpublished(self):
        Product.objects.filter(pk=self.p1.pk).update(status=Product.Status.REJECTED)
        self.place_order()
        self.assertEqual(Order.objects.count(), 0)

    def test_failed_reservation_rolls_back_whole_order(self):
        """If the second item cannot be reserved, the first item's stock is restored."""
        original = Product.objects.filter

        calls = {"n": 0}

        def flaky_filter(*args, **kwargs):
            queryset = original(*args, **kwargs)
            if "quantity__gte" in kwargs:
                calls["n"] += 1
                if calls["n"] == 2:
                    return queryset.none()
            return queryset

        with mock.patch.object(Product.objects, "filter", side_effect=flaky_filter):
            with self.assertRaises(services.CheckoutError):
                services.create_order(self.customer, SHIPPING)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity, 5)

    def test_payment_marks_order_paid_and_notifies(self):
        self.place_order()
        order = Order.objects.get()
        response = self.client.post(reverse("orders:pay", args=[order.pk]))
        self.assertRedirects(response, reverse("orders:detail", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        payment = order.payments.get()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertIsNotNone(payment.paid_at)
        self.assertTrue(Notification.objects.filter(user=self.seller_user, message__contains=order.reference).exists())

    def test_paying_twice_is_rejected(self):
        self.place_order()
        order = Order.objects.get()
        self.client.post(reverse("orders:pay", args=[order.pk]))
        self.client.post(reverse("orders:pay", args=[order.pk]))
        self.assertEqual(Payment.objects.filter(order=order, status=Payment.Status.PAID).count(), 1)
        with self.assertRaises(services.PaymentError):
            services.pay_order(order)

    def test_cancelled_order_cannot_be_paid_and_stock_returns(self):
        self.place_order()
        order = Order.objects.get()
        self.client.post(reverse("orders:cancel", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual((self.p1.quantity, self.p2.quantity), (5, 2))
        self.client.post(reverse("orders:pay", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertFalse(Payment.objects.filter(order=order, status=Payment.Status.PAID).exists())

    def test_paid_order_cannot_be_cancelled(self):
        self.place_order()
        order = Order.objects.get()
        self.client.post(reverse("orders:pay", args=[order.pk]))
        self.client.post(reverse("orders:cancel", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.quantity, 3)  # stock was not returned

    def test_failed_payment_keeps_order_unpaid_and_allows_retry(self):
        self.place_order()
        order = Order.objects.get()
        with mock.patch("orders.services.get_gateway") as gateway:
            gateway.return_value.redirect_based = False  # simulated (non-redirect) gateway
            gateway.return_value.charge.return_value = False
            response = self.client.post(reverse("orders:pay", args=[order.pk]), follow=True)
        self.assertContains(response, "Payment failed")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(order.payments.filter(status=Payment.Status.FAILED).count(), 1)
        self.assertEqual(order.payments.filter(status=Payment.Status.PENDING).count(), 1)
        self.client.post(reverse("orders:pay", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)

    def test_pay_and_cancel_require_post(self):
        self.place_order()
        order = Order.objects.get()
        self.assertEqual(self.client.get(reverse("orders:pay", args=[order.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("orders:cancel", args=[order.pk])).status_code, 405)

    def test_test_payment_is_labelled(self):
        self.place_order()
        order = Order.objects.get()
        self.assertContains(self.client.get(reverse("orders:detail", args=[order.pk])), "Test mode")


class OrderAccessTests(BaseTestCase):
    def setUp(self):
        self.seller_user, self.shop = make_seller()
        self.product = make_product(self.shop)
        self.alice = make_customer("alice")
        self.bob = make_customer("bob")
        self.order = Order.objects.create(customer=self.alice, total_amount=Decimal("1000"), **{
            "shipping_name": "A", "shipping_phone": "1", "shipping_address": "x", "shipping_city": "y"})

    def test_other_customers_cannot_view_pay_or_cancel(self):
        self.login(self.bob)
        self.assertEqual(self.client.get(reverse("orders:detail", args=[self.order.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("orders:pay", args=[self.order.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("orders:cancel", args=[self.order.pk])).status_code, 404)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PENDING_PAYMENT)

    def test_order_list_shows_only_own_orders(self):
        Order.objects.create(customer=self.bob, total_amount=Decimal("5"), shipping_name="B",
                             shipping_phone="1", shipping_address="x", shipping_city="y")
        self.login(self.alice)
        page = self.client.get(reverse("orders:list"))
        self.assertEqual([o.pk for o in page.context["page_obj"]], [self.order.pk])

    def test_anonymous_redirected_and_sellers_forbidden(self):
        self.assertEqual(self.client.get(reverse("orders:detail", args=[self.order.pk])).status_code, 302)
        self.login(self.seller_user)
        self.assertEqual(self.client.get(reverse("orders:detail", args=[self.order.pk])).status_code, 403)

    def test_order_references_are_unique_and_generated(self):
        self.assertTrue(self.order.reference.startswith("ORD-"))
        other = Order.objects.create(customer=self.alice, total_amount=Decimal("1"), shipping_name="A",
                                     shipping_phone="1", shipping_address="x", shipping_city="y")
        self.assertNotEqual(self.order.reference, other.reference)

    def test_database_rejects_negative_total(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Order.objects.create(customer=self.alice, total_amount=Decimal("-1"), shipping_name="A",
                                     shipping_phone="1", shipping_address="x", shipping_city="y")


class SellerFulfillmentTests(BaseTestCase):
    def setUp(self):
        self.seller_user, self.shop = make_seller("sellera")
        self.rival_user, self.rival_shop = make_seller("sellerb")
        self.product = make_product(self.shop)
        self.customer = make_customer("buyer")
        self.order = Order.objects.create(
            customer=self.customer, status=Order.Status.PAID, total_amount=Decimal("1000"),
            shipping_name="B", shipping_phone="1", shipping_address="x", shipping_city="y",
        )
        self.item = OrderItem.objects.create(
            order=self.order, product=self.product, seller=self.shop, product_name="Test product",
            seller_name=self.shop.shop_name, unit_price=Decimal("1000"), quantity=1,
        )

    def update(self, status):
        return self.client.post(reverse("orders:seller_item_update", args=[self.item.pk]), {"status": status})

    def test_seller_advances_item_through_flow_and_customer_is_notified(self):
        self.login(self.seller_user)
        for status in ("processing", "shipped", "delivered"):
            self.update(status)
            self.item.refresh_from_db()
            self.assertEqual(self.item.fulfillment_status, status)
        self.assertEqual(Notification.objects.filter(user=self.customer).count(), 3)

    def test_cannot_skip_steps_or_use_unknown_status(self):
        self.login(self.seller_user)
        self.update("delivered")
        self.update("hacked")
        self.update("cancelled")
        self.item.refresh_from_db()
        self.assertEqual(self.item.fulfillment_status, OrderItem.Fulfillment.PENDING)

    def test_unpaid_orders_cannot_be_fulfilled(self):
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.PENDING_PAYMENT)
        self.login(self.seller_user)
        self.update("processing")
        self.item.refresh_from_db()
        self.assertEqual(self.item.fulfillment_status, OrderItem.Fulfillment.PENDING)

    def test_other_seller_cannot_update_item(self):
        self.login(self.rival_user)
        self.assertEqual(self.update("processing").status_code, 404)
        self.item.refresh_from_db()
        self.assertEqual(self.item.fulfillment_status, OrderItem.Fulfillment.PENDING)

    def test_seller_order_list_only_shows_own_paid_items(self):
        rival_product = make_product(self.rival_shop, name="Rival thing")
        OrderItem.objects.create(
            order=self.order, product=rival_product, seller=self.rival_shop, product_name="Rival thing",
            seller_name="Rival", unit_price=Decimal("5"), quantity=1,
        )
        self.login(self.seller_user)
        page = self.client.get(reverse("orders:seller_list"))
        self.assertEqual([i.product_name for i in page.context["page_obj"]], ["Test product"])

    def test_customer_cannot_use_seller_fulfilment(self):
        self.login(self.customer)
        self.assertEqual(self.update("processing").status_code, 403)

    def test_order_history_survives_product_deletion(self):
        self.product.delete()
        self.item.refresh_from_db()
        self.assertIsNone(self.item.product)
        self.assertEqual(self.item.product_name, "Test product")
        self.login(self.customer)
        page = self.client.get(reverse("orders:detail", args=[self.order.pk]))
        self.assertContains(page, "Test product")
