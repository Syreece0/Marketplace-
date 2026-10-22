"""Payment gateway integration point.

``PAYMENT_GATEWAY=test`` (the default) uses :class:`TestGateway`, a clearly
labelled test workflow in which no real money moves. To accept real payments,
add a subclass of :class:`BaseGateway` that talks to your provider's API
(using PAYMENT_PUBLIC_KEY / PAYMENT_SECRET_KEY from the environment), register
it in ``GATEWAYS`` and set ``PAYMENT_GATEWAY`` to its name. See README.md.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class BaseGateway:
    name = ""
    label = ""
    is_test = False

    def charge(self, payment):
        """Attempt to collect ``payment``. Return True when paid, False otherwise."""
        raise NotImplementedError


class TestGateway(BaseGateway):
    __test__ = False  # stop test runners collecting this class

    name = "test"
    label = "Test payment (no real money is charged)"
    is_test = True

    def charge(self, payment):
        return True


GATEWAYS = {TestGateway.name: TestGateway}


def get_gateway():
    try:
        return GATEWAYS[settings.PAYMENT_GATEWAY]()
    except KeyError:
        raise ImproperlyConfigured(
            f"Unknown PAYMENT_GATEWAY '{settings.PAYMENT_GATEWAY}'. "
            f"Available: {', '.join(GATEWAYS)}."
        )
