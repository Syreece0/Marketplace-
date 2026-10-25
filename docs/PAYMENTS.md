# Real payments with Paystack

## How money flows

| Who | Gets | Pays |
| --- | --- | --- |
| Seller | 90% of their items, straight to their bank account | nothing |
| Administrator | 10% commission | Paystack's transaction fee (taken from the 10%) |
| Customer | the goods | the listed price, nothing extra |

The percentage is `COMMISSION_PERCENT` (default 10). The commission and the seller's earnings are copied onto
each order item at purchase time, so changing the rate later never alters old orders.
The marketplace never holds sellers' money: Paystack splits each payment (`bearer_type: account`, so the
administrator's account bears the fee) and settles each seller's share on its normal schedule.

## Going live: checklist

1. Test first: Paystack dashboard -> **Test mode** -> copy the **test** secret key. Set in Render:
   `PAYMENT_GATEWAY=paystack`, `PAYSTACK_SECRET_KEY=sk_test_...`, `PAYSTACK_PUBLIC_KEY=pk_test_...`.
2. Create and commit the new migrations (this update adds database fields):
   `python manage.py makemigrations accounts orders` then commit the new files in `migrations/`.
3. In Paystack -> **Settings -> API Keys & Webhooks**, set the **Webhook URL** (for test and for live) to
   `https://YOUR-SITE/payments/paystack/webhook/`.
4. Every seller opens **Payout account**, picks their bank and enters their 10-digit account number. The
   account name is verified with the bank and a Paystack sub-account is created. Until this is done, that
   shop's products cannot be added to carts.
5. Place a test order with Paystack's test cards and check: order becomes *Paid*, the seller sees
   "You earn" = 90%, the admin dashboard shows the commission.
6. When happy: switch to the **live** keys (`sk_live_...`, `pk_live_...`). Live mode needs your Paystack
   business to be activated.

## Refunds (administrator)

1. Refund the customer in the **Paystack dashboard** (Transactions -> the payment -> Refund).
2. In the Django admin (`/django-admin/`) open **Orders**, tick the order and run
   **Record refund**. This marks the order and payment as refunded, cancels its items and notifies the
   customer and sellers. It does not move money by itself.
3. Paystack decides how a refund interacts with split settlements (whether the seller's share is
   recovered). Check Paystack's current refund rules for split payments and agree the policy with sellers.

If a customer pays for an order that was cancelled or already paid, the administrators get a notification
asking them to refund that payment.

## Safety design

- An order is marked paid only after the server asks Paystack for the real result and the amount and currency
  match. The URL the customer returns to, and the webhook message, are never trusted on their own.
- Webhooks must carry a valid HMAC-SHA512 signature (`x-paystack-signature`) or they are rejected.
- Confirmation is idempotent: the browser return and the webhook can both arrive, in either order.
- Every payment attempt uses a new reference. Card details never touch this site.
- One order can include at most `PAYSTACK_MAX_SELLERS_PER_ORDER` shops (default 5); check Paystack's current
  split limits before raising it.

## Limits to know about

- Not run against the real Paystack API in development: the tests use a fake. Test mode with your own test
  keys is the real check (step 5 above).
- Paystack's exact fees, settlement times and refund rules change; read their pricing and documentation.
- Tax and legal duties of running a commission marketplace are yours to confirm with a professional.
