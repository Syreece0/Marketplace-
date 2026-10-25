"""Payment gateways.

``PAYMENT_GATEWAY=test`` (default) is a clearly labelled simulation in which no money moves.
``PAYMENT_GATEWAY=paystack`` takes real payments through Paystack and splits every payment:
each seller's share goes straight to their own bank account, and the rest (the marketplace
commission) stays with the administrator's Paystack account, which also bears Paystack's fee.
"""
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from . import paystack


class BaseGateway:
    name = ""
    label = ""
    is_test = False
    #: True when the customer must be sent to the provider's page to pay.
    redirect_based = False
    #: True when sellers need a verified payout account before their products can be sold.
    requires_seller_payout_setup = False

    def charge(self, payment):
        """Simulated gateways only: collect ``payment`` immediately. Return True when paid."""
        raise NotImplementedError

    def initialize(self, payment, callback_url):
        """Redirect-based gateways: return the URL to send the customer to."""
        raise NotImplementedError

    def verify(self, payment):
        """Redirect-based gateways: return ``"paid"``, ``"failed"`` or ``"pending"``."""
        raise NotImplementedError


class TestGateway(BaseGateway):
    __test__ = False  # stop test runners collecting this class

    name = "test"
    label = "Test payment (no real money is charged)"
    is_test = True

    def charge(self, payment):
        return True


class PaystackGateway(BaseGateway):
    name = "paystack"
    label = "Paystack"
    redirect_based = True
    requires_seller_payout_setup = True

    @staticmethod
    def build_split(order):
        """Per-seller shares in kobo. Whatever is not listed stays with the administrator."""
        shares = defaultdict(lambda: Decimal("0.00"))
        for item in order.items.select_related("seller"):
            if item.seller_id and item.seller.paystack_subaccount_code:
                shares[item.seller.paystack_subaccount_code] += item.seller_earnings
        return {
            "type": "flat",
            # The administrator's (main) account pays Paystack's transaction fee.
            "bearer_type": "account",
            "subaccounts": [
                {"subaccount": code, "share": paystack.to_kobo(amount)}
                for code, amount in sorted(shares.items())
                if amount > 0
            ],
        }

    def initialize(self, payment, callback_url):
        order = payment.order
        return paystack.initialize_transaction(
            email=order.customer.email,
            amount=payment.amount,
            reference=payment.reference,
            callback_url=callback_url,
            currency=payment.currency,
            split=self.build_split(order),
            metadata={"order_reference": order.reference},
        )

    def verify(self, payment):
        data = paystack.verify_transaction(payment.reference)
        state = data.get("status")
        if state == "success":
            same_amount = int(data.get("amount") or 0) == paystack.to_kobo(payment.amount)
            same_currency = (data.get("currency") or payment.currency) == payment.currency
            if not (same_amount and same_currency):
                # Never credit an order when the paid amount differs from what we asked for.
                return "failed"
            return "paid"
        if state in {"failed", "reversed"}:
            return "failed"
        # "abandoned", "ongoing", "pending"...: the customer may still finish paying.
        return "pending"


GATEWAYS = {TestGateway.name: TestGateway, PaystackGateway.name: PaystackGateway}


def get_gateway():
    try:
        return GATEWAYS[settings.PAYMENT_GATEWAY]()
    except KeyError:
        raise ImproperlyConfigured(
            f"Unknown PAYMENT_GATEWAY '{settings.PAYMENT_GATEWAY}'. "
            f"Available: {', '.join(GATEWAYS)}."
        )
