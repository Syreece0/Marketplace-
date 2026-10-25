"""Small Paystack API client (standard library only, no extra packages).

Only the calls this marketplace needs: bank list, account-name lookup,
seller sub-accounts, starting a split payment and verifying it.
The secret key is read from settings and is never logged.
"""
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("marketplace")


class PaystackError(Exception):
    """Raised with a message that is safe to show to the user."""


def to_kobo(amount):
    """Convert a naira Decimal to the integer number of kobo Paystack expects."""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _call(method, path, payload=None, timeout=20):
    """Send one request and return the decoded ``data`` of a successful reply."""
    secret = settings.PAYMENT_SECRET_KEY
    if not secret:
        raise PaystackError("Online payments are not configured yet.")
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        settings.PAYSTACK_BASE_URL + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Paystack sits behind a firewall that rejects Python's default "Python-urllib" agent.
            "User-Agent": "Mozilla/5.0 (compatible; MarketplaceServer/1.0)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https host)
            result = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        message = ""
        try:
            message = json.loads(error.read().decode()).get("message", "")
        except (ValueError, OSError):
            pass
        logger.warning("Paystack %s %s failed: HTTP %s %s", method, path.split("?")[0], error.code, message)
        raise PaystackError(message or "The payment provider rejected the request.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        logger.warning("Paystack %s %s unreachable: %s", method, path.split("?")[0], error)
        raise PaystackError("Could not reach the payment provider. Please try again.") from error
    except ValueError as error:
        raise PaystackError("The payment provider sent an unreadable reply.") from error
    if not result.get("status"):
        raise PaystackError(result.get("message") or "The payment provider reported an error.")
    return result.get("data")


# ---------------------------------------------------------------- banks ----
def list_banks():
    """Return ``[(code, name), ...]`` for Nigerian banks (cached for a day)."""
    banks = cache.get("paystack_banks")
    if banks is None:
        data = _call("GET", "/bank?country=nigeria&currency=NGN&perPage=200&use_cursor=false")
        banks = sorted(
            {(bank["code"], bank["name"]) for bank in data or [] if bank.get("code") and bank.get("name")},
            key=lambda pair: pair[1].lower(),
        )
        if banks:
            cache.set("paystack_banks", banks, 60 * 60 * 24)
    return banks


def resolve_account(account_number, bank_code):
    """Return the account holder's name, or raise PaystackError if it cannot be verified."""
    query = urllib.parse.urlencode({"account_number": account_number, "bank_code": bank_code})
    data = _call("GET", f"/bank/resolve?{query}")
    name = (data or {}).get("account_name", "")
    if not name:
        raise PaystackError("We could not verify that account. Check the bank and account number.")
    return name


# ---------------------------------------------------------- subaccounts ----
def _subaccount_payload(business_name, bank_code, account_number):
    return {
        "business_name": business_name,
        "settlement_bank": bank_code,
        "account_number": account_number,
        # Sub-account default only; real splits are set per payment in initialize_transaction().
        "percentage_charge": float(settings.COMMISSION_PERCENT),
    }


def create_subaccount(business_name, bank_code, account_number):
    data = _call("POST", "/subaccount", _subaccount_payload(business_name, bank_code, account_number))
    return data["subaccount_code"]


def update_subaccount(code, business_name, bank_code, account_number):
    _call("PUT", f"/subaccount/{urllib.parse.quote(code, safe='')}",
          _subaccount_payload(business_name, bank_code, account_number))
    return code


# ---------------------------------------------------------- transactions ----
def initialize_transaction(*, email, amount, reference, callback_url, currency, split, metadata=None):
    """Start a payment. Returns the Paystack page URL the customer must be sent to."""
    payload = {
        "email": email,
        "amount": to_kobo(amount),
        "currency": currency,
        "reference": reference,
        "callback_url": callback_url,
        "split": split,
    }
    if metadata:
        payload["metadata"] = metadata
    return _call("POST", "/transaction/initialize", payload)["authorization_url"]


def verify_transaction(reference):
    """Ask Paystack for the real outcome of a payment. Returns its ``data`` dict."""
    return _call("GET", f"/transaction/verify/{urllib.parse.quote(reference, safe='')}")


def valid_signature(raw_body, header_value):
    """Check the ``x-paystack-signature`` header of a webhook (HMAC-SHA512 of the raw body)."""
    secret = settings.PAYMENT_SECRET_KEY
    if not secret or not header_value:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, header_value.strip())
