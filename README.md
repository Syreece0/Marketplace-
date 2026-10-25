# Tradewind marketplace

A Django online marketplace with three account types (customers, sellers, administrators), seller and
listing approval, product requests, wishlist, downloads (image and PDF info sheet), cart, orders with a
clearly labelled **test-payment** workflow, notifications, English/French interface, role dashboards and
automated tests.

> **Read this first: what has and has not been verified**
>
> This project was written in an environment where Django could not be installed (the package index was
> blocked), so **the code has never been executed and the test suite has never been run**. What *was*
> checked: every Python file compiles, there are no undefined names (pyright), every `{% url %}` name,
> `{% include %}`, `{% extends %}` and template block pair is consistent, and the French `.mo` catalogue
> loads and translates correctly. **Migration files are not included**, because they have to be generated
> by Django. Expect to fix a few small errors on first run. Steps 6 and 8 below tell you how to find them.

---

## 1. Requirements

- Python 3.11 or newer (3.12/3.13 are fine). Check with `python --version`.
- Visual Studio Code with the *Python* extension.
- An internet connection in the browser (Bootstrap, Bootstrap Icons and the Inter font load from CDNs).

## 2. Open the project in VS Code

1. Unzip the project somewhere simple, e.g. `C:\Projects\marketplace`.
2. VS Code → **File → Open Folder…** → choose the `marketplace` folder (the one containing `manage.py`).
3. Open the integrated terminal: **Terminal → New Terminal**.

## 3. Create and activate a virtual environment

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell refuses with "running scripts is disabled", run this once and try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. (Or use Command Prompt: `.venv\Scripts\activate.bat`.)

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

When it works, your prompt starts with `(.venv)`. In VS Code press **Ctrl+Shift+P → "Python: Select
Interpreter"** and pick the one inside `.venv`.

## 4. Install the packages

```bash
pip install -r requirements.txt
```

## 5. Create your settings file

```powershell
copy .env.example .env        # macOS/Linux: cp .env.example .env
```

Open `.env` and set `DJANGO_SECRET_KEY` to a long random value. Generate one with:

```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

Leave `DJANGO_DEBUG=True` while developing. The project **refuses to start without a secret key when
DEBUG is off**, on purpose.

## 6. Create the database (migrations)

There are no migration files yet. Generate them, then apply them:

```bash
python manage.py makemigrations accounts products requests_app orders wishlist notifications
python manage.py migrate
```

`accounts` must come first because the project uses a custom user model (`accounts.User`). Listing the
apps like this guarantees that. If `makemigrations` reports an error, it will name the file and line.

Optional starter categories (categories only, no fake users or products):

```bash
python manage.py seed_categories
```

## 7. Create the administrator

```bash
python manage.py createsuperuser
```

There is **no built-in admin password**. Accounts made this way automatically get the *Administrator*
role. Sign in at `/accounts/login/`; you land on `/manage/`. Django's own admin is at `/django-admin/`.

## 8. Run the tests

```bash
python manage.py test
```

Run one app only with e.g. `python manage.py test orders`. Tests use a temporary database and a temporary
media folder, so they never touch your data. **Please run this before anything else and fix what it
reports**; the tests were written carefully but never executed (see the warning at the top).

## 9. Start the website

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. Stop the server with **Ctrl+C**.

### Try the full flow

1. Register a **seller** account (`/accounts/register/seller/`). It starts as *pending*.
2. Sign in as the administrator → **Seller approvals** → set the shop to *Approved*.
3. Sign in as the seller → **Add product**. It starts as *pending*.
4. As administrator → **Products** → *Publish* it.
5. Register a **customer**, browse, save to the wishlist, send a request, add to cart, check out and press
   *Pay now* (test payment, no real money).
6. As the seller, open **Orders** and advance the item: processing → shipped → delivered.

## 10. French / English

The navigation bar has a language switcher. The French catalogue is in `locale/fr/LC_MESSAGES/django.po`
and is already compiled to `django.mo`. After editing the `.po` file, recompile it with:

```bash
python scripts/compile_messages.py
```

(This pure-Python script replaces `manage.py compilemessages`, which needs GNU gettext, awkward on Windows.)

What is translated: all interface text, buttons, flash messages and validation messages written for
this project (about 620 strings), plus Django's own built-in messages. What is **not**
translated, deliberately: user-generated content (product names, descriptions, shop names, reviews,
messages), as the spec requires. The PDF info sheet and the password-reset email text are English only.

To add a new language or new strings: install GNU gettext and run `python manage.py makemessages -l <code>`.

## 11. Common problems

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'django'` | The virtual environment is not active. Re-run step 3. |
| `ImproperlyConfigured: DJANGO_SECRET_KEY is not set` | Do step 5 (create `.env`). |
| `no such table` / `relation does not exist` | Run step 6 (`makemigrations`, then `migrate`). |
| `Manager isn't available; 'auth.User' has been swapped` | You ran an old migration set. Delete `db.sqlite3` and every `migrations/0*.py` file, then redo step 6. |
| Pages have no styling | You are offline (CDN files) or `DEBUG` is off without running `collectstatic`. |
| Uploaded images give 404 | Media is only served by Django when `DJANGO_DEBUG=True`. See `docs/DEPLOYMENT.md` for production. |
| Emails do not arrive | By default they print in the terminal. Set `EMAIL_*` in `.env` for real email. |
| Port already in use | `python manage.py runserver 8001` |

## 12. Project layout

```
config/            settings, root URLs, WSGI/ASGI
core/              public pages, shared forms/validators/permissions, template tags, test factories
accounts/          custom User (roles), profiles, seller profile, auth views, shop settings
products/          categories, products, gallery images, reviews, reports, browsing, seller tools, downloads, PDF
requests_app/      customer-to-seller product requests and the status workflow
wishlist/          saved products
orders/            cart, orders, order items, payments, payment gateway interface, fulfilment
notifications/     in-app notifications
dashboard/         customer, seller and administrator dashboards and management pages
templates/         base layout, partials (includes/), role layout (layouts/), one folder per app
static/            CSS design system, JavaScript, placeholder image
locale/fr/         French translation
scripts/           compile_messages.py
docs/              ARCHITECTURE.md, DEPLOYMENT.md
```

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Going live: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## 13. What is implemented, and what is not

Implemented (in code, not yet executed): everything listed in sections 15-31 of your specification that
was available to me, namely the design system and responsive layouts, database models with constraints and
indexes, the project structure, authentication and role-based authorisation, security measures, the admin
tools, required pages and empty/loading/error states, SEO and accessibility basics, deployment preparation,
tests, and deliverables.

Not implemented / needs your decision:

- **Real payments.** Paystack with a 10% commission is implemented; see `docs/PAYMENTS.md`. It is off until you set `PAYMENT_GATEWAY=paystack` and add your keys, and it has not been tried against the live Paystack service.
- **Buyer-seller chat messaging.** The spec calls it optional ("if implementing"); product requests with a
  seller reply cover the communication. There is no `Message` model.
- **Sections 1-14 of your specification** were not in the file I received (it began mid-way, at the end of
  the translation section). Anything those sections required is missing. See the notes in the final report.
- Product images are stored as uploaded (no thumbnail generation); cards use CSS cropping.
- Currency defaults to Nigerian naira (`CURRENCY_*` in `.env`); change it there.
- The legal pages (terms, privacy) are **template text** and must be reviewed by a professional.
