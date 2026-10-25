"""Forget every seller's saved Paystack sub-account.

Run this once when you switch from Paystack TEST keys to LIVE keys. Test sub-accounts do not
exist in live mode, so each seller must open "Payout account" again and save their bank details.
Until they do, their products cannot be bought (which is safer than a failed payment).
"""
from django.core.management.base import BaseCommand

from accounts.models import SellerProfile


class Command(BaseCommand):
    help = "Clear all saved seller payout accounts (use when switching Paystack test <-> live)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")

    def handle(self, *args, **options):
        count = SellerProfile.objects.exclude(paystack_subaccount_code="").count()
        if not options["yes"]:
            answer = input(f"This clears the payout account of {count} shop(s). Type 'yes' to continue: ")
            if answer.strip().lower() != "yes":
                self.stdout.write("Cancelled.")
                return
        SellerProfile.objects.update(
            bank_code="", bank_name="", account_number="", account_name="", paystack_subaccount_code=""
        )
        self.stdout.write(self.style.SUCCESS(f"Cleared {count} payout account(s)."))
