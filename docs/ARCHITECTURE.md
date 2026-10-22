# Architecture

## Apps and responsibilities

| App | Owns | Notes |
| --- | --- | --- |
| `accounts` | `User` (custom, `role` field), `UserProfile`, `SellerProfile` | One user table for all roles. Role helpers (`is_customer`, `is_seller`, `is_marketplace_admin`, `is_approved_seller`) are the only place role logic lives. |
| `products` | `Category`, `Product`, `ProductImage`, `Review`, `Report` | `Product.objects.public()` is the single definition of "visible to customers". PDF sheet in `pdf.py`. |
| `requests_app` | `ProductRequest` | Status workflow is a transition table on the model (`TRANSITIONS`). |
| `wishlist` | `WishlistItem` | Unique (user, product) constraint. |
| `orders` | `Cart`, `CartItem`, `Order`, `OrderItem`, `Payment` | All business rules in `services.py`; views are thin. Gateway interface in `gateways.py`. |
| `notifications` | `Notification` | Created through `notifications.services.notify()`. |
| `dashboard` | no models | Role dashboards and admin management pages. |
| `core` | no models | Public pages, shared form mixin, validators, permission decorators, template tags, test factories. |

## Entity relationships (simplified)

```
User 1--1 UserProfile
User 1--1 SellerProfile 1--* Product *--1 Category
Product 1--* ProductImage
User(customer) 1--1 Cart 1--* CartItem *--1 Product
User(customer) 1--* Order 1--* OrderItem  (copies name, price, seller name)
Order 1--* Payment
User(customer) 1--* ProductRequest *--1 Product, *--1 SellerProfile (must own the product)
User(customer) 1--* WishlistItem *--1 Product
User(customer) 1--* Review *--1 Product (one per customer+product)
User 1--* Report *--1 Product
User 1--* Notification
```

## Roles and access

- **Customer**: browse, wishlist, cart, orders, requests, reviews, reports.
- **Seller**: own shop and products (only after approval), requests addressed to them, fulfilment of
  their own order items. Sees delivery details only for paid orders that contain their products.
- **Administrator** (`role=admin` or superuser): approvals, moderation, users, categories, orders (read), reports.
  A plain `is_staff` flag does **not** grant access to the custom admin pages.

Every protected view uses a decorator from `core/permissions.py`: anonymous users go to the login page,
users with the wrong role get a 403 page. Object access is scoped in the query itself
(`get_object_or_404(Order, pk=pk, customer=request.user)`), so other users' objects return 404.

## Approval workflow

```
Seller registers -> SellerProfile.pending -> admin sets approved / rejected / suspended (seller notified)
Approved seller creates Product -> pending -> admin publishes / rejects with reason (seller notified)
Editing name/description/image/category on a published listing -> back to pending
Products appear publicly only when: product published AND shop approved AND owner active AND category active
```

## Order and payment flow

```
Cart --checkout--> Order(pending_payment) + OrderItems + Payment(pending)   [one transaction; stock reserved
                                                                           with a guarded UPDATE]
pending_payment --pay--> paid        (Payment paid, notifications to customer and sellers)
pending_payment --cancel--> cancelled (stock returned, payment cancelled)
paid items: pending -> processing -> shipped -> delivered (seller advances own items only)
```

Prices come from the database at checkout and are copied onto `OrderItem`. Nothing price-related is read
from the browser. Row locks (`select_for_update`) are used on PostgreSQL; SQLite serialises writes anyway.

## Security measures (and where)

- CSRF: Django middleware on all POST forms; AJAX sends the token header.
- Authentication: Django hashers; 10-character minimum plus similarity/common/numeric validators.
- Mass assignment: forms list allowed fields explicitly; status, owner and role are set in views.
- Uploads: size, extension and real content validated (`core/validators.py`); stored under `media/`.
- Open redirects: `core.utils.safe_next_url` validates every `next` target.
- XSS: templates auto-escape; user text is never marked safe.
- Logging: important actions go to the `marketplace` logger (`logs/marketplace.log`).
- Headers/cookies: `nosniff`, `X-Frame-Options: DENY`, HttpOnly/SameSite cookies; HTTPS settings switch on
  with `DJANGO_USE_HTTPS=True`.
- Secrets only from environment variables; the app refuses to start without a key when DEBUG is off.

## Design system

`static/css/main.css` defines the palette as CSS variables (`--tw-primary` #172554 and so on), overrides
Bootstrap's variables, and holds the reusable components (buttons, cards, status badges, stat cards, empty
states, sidebar, pagination, modal). Motion is subtle and disabled under `prefers-reduced-motion`.
`static/js/main.js` adds optional enhancements (AJAX wishlist heart, confirm dialog, loading buttons,
gallery, notification badge refresh). Every one of them has a working no-JavaScript fallback.
