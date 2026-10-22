# Deployment guide

This project is **prepared** for deployment, not deployed. Having the tests pass does not make a site
production-secure; work through the checklist below and review the legal pages before launch.

## Checklist

- [ ] Generate a new `DJANGO_SECRET_KEY` (never reuse the development one).
- [ ] `DJANGO_DEBUG=False`.
- [ ] `DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com`.
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com`.
- [ ] Serve over HTTPS, then set `DJANGO_USE_HTTPS=True` (secure cookies, HSTS, HTTP→HTTPS redirect).
      If you sit behind a proxy that terminates TLS, make sure it sends `X-Forwarded-Proto`.
- [ ] Use PostgreSQL: `DB_ENGINE=postgresql` and `DB_NAME/USER/PASSWORD/HOST/PORT`; `pip install "psycopg[binary]"`.
- [ ] Real email: `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`,
      `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`, `CONTACT_EMAIL`.
- [ ] `python manage.py migrate`, `python manage.py collectstatic --noinput`, `python manage.py createsuperuser`.
- [ ] Run with a production server (e.g. `pip install gunicorn`, then `gunicorn config.wsgi`) behind
      nginx/Caddy or your host's platform. Do not use `runserver`.
- [ ] Run `python manage.py check --deploy` and fix what it reports.
- [ ] Replace the template Terms and Privacy text with reviewed versions.
- [ ] Decide how real payments will work (below).

## Configuration reference

| Setting | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | Signs sessions, tokens and reset links. Keep private. |
| `DJANGO_DEBUG` | Must be `False` in production. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated host names the site may be served from. |
| `DB_*` | Database engine and credentials. SQLite is for development only. |
| `EMAIL_*` | SMTP for password resets and the contact form. |
| `SITE_NAME`, `CURRENCY_CODE`, `CURRENCY_SYMBOL` | Branding and currency. |
| `MAX_IMAGE_UPLOAD_MB` | Upload size limit (default 5). |
| `PAYMENT_GATEWAY`, `PAYMENT_PUBLIC_KEY`, `PAYMENT_SECRET_KEY` | Payment provider selection and credentials. |

## Static files

WhiteNoise serves the collected files from `staticfiles/` (run `collectstatic`). Nothing else is needed.

## Media files (user uploads): needs a strategy

Product images, logos and avatars are written to `media/`. Django only serves that folder when
`DJANGO_DEBUG=True`. In production you must serve it yourself (nginx `location /media/`) **or** move to
object storage (S3, Cloudflare R2, etc. via `django-storages`).

Many hosts use a **temporary filesystem** that is wiped on every deploy or restart; uploads stored there
will disappear. Use a persistent disk or object storage, and include it in your backups.

## Backups

- Database: schedule `pg_dump` (or your host's snapshots) at least daily; keep copies off the server.
- Media: back up the uploads folder or bucket (versioning helps).
- Test a restore at least once. A backup you have never restored is a guess.
- Keep `.env` in a password manager or secret store, not in git.

## Logging

Logs go to the console and to `logs/marketplace.log` (rotating, 5 files of 5 MB). Business and admin
actions (orders, approvals, moderation, account changes) are logged by the `marketplace` logger. On a
managed host, prefer the console output and let the platform collect it. Watch for `ERROR` lines and
set up error alerts (e.g. Sentry) before launch.

## Adding a real payment provider

1. Create a class in `orders/gateways.py` extending `BaseGateway` with `name`, `label` and `charge(payment)`.
   For redirect-based providers (Paystack, Flutterwave, Stripe Checkout) you will normally start a hosted
   payment in `charge()` and confirm it in a **webhook view** that verifies the provider's signature
   before calling `orders.services.pay_order`-style logic. Never mark an order paid from a browser request.
2. Register it in `GATEWAYS` and set `PAYMENT_GATEWAY=<name>` plus keys in `.env`.
3. Never store card numbers; keep only the provider's references (the `Payment` model is built for this).
4. Add tests for success, failure, duplicate webhooks and tampered signatures.
