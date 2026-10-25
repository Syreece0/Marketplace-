"""
Django settings for the Tradewind marketplace.

All secrets and environment-specific values come from environment variables
(optionally loaded from a local ".env" file). See .env.example.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core security settings
# --------------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", False)
RUNNING_TESTS = "test" in sys.argv

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or RUNNING_TESTS:
        # Throw-away key, only acceptable for local development and tests.
        SECRET_KEY = "insecure-development-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is not set. Copy .env.example to .env and set it."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

USE_HTTPS = env_bool("DJANGO_USE_HTTPS", False)
if USE_HTTPS:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # two weeks
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Project apps
    "core",
    "accounts",
    "products",
    "requests_app",
    "orders",
    "wishlist",
    "notifications",
    "dashboard",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()  # Render/Heroku style connection string
# Writing DB_ENGINE=sqlite explicitly (e.g. in a local .env) always wins over DATABASE_URL, so a
# stray DATABASE_URL on your computer can never point local work at the live database.
if DATABASE_URL.startswith(("postgres://", "postgresql://")) and os.environ.get("DB_ENGINE", "").strip().lower() != "sqlite":
    from urllib.parse import unquote, urlparse

    _db = urlparse(DATABASE_URL)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(_db.path.lstrip("/")),
            "USER": unquote(_db.username or ""),
            "PASSWORD": unquote(_db.password or ""),
            "HOST": _db.hostname or "localhost",
            "PORT": str(_db.port or 5432),
            "CONN_MAX_AGE": 60,
        }
    }
elif os.environ.get("DB_ENGINE", "sqlite").lower() in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "marketplace"),
            "USER": os.environ.get("DB_USER", ""),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:logged_out"
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # reset links valid for 24 hours

# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("fr", "Français"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static and media files
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(exist_ok=True)  # avoids a WhiteNoise warning before collectstatic is run

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Cloudinary: on hosts with a temporary disk (Render, Heroku...) uploaded files vanish on every
# deploy/restart, so store them in Cloudinary instead. Enabled only when CLOUDINARY_URL is set
# (format: cloudinary://API_KEY:API_SECRET@CLOUD_NAME).
# Either set CLOUDINARY_URL, or the three separate variables CLOUDINARY_CLOUD_NAME,
# CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET.
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "").strip()
_cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
_api_key = os.environ.get("CLOUDINARY_API_KEY", "").strip()
_api_secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
if not CLOUDINARY_URL and _cloud_name and _api_key and _api_secret:
    CLOUDINARY_URL = f"cloudinary://{_api_key}:{_api_secret}@{_cloud_name}"
    os.environ["CLOUDINARY_URL"] = CLOUDINARY_URL
USE_CLOUDINARY = CLOUDINARY_URL.startswith("cloudinary://")
if USE_CLOUDINARY:
    if _cloud_name and _api_key and _api_secret:
        CLOUDINARY_STORAGE = {
            "CLOUD_NAME": _cloud_name,
            "API_KEY": _api_key,
            "API_SECRET": _api_secret,
        }
    # Only the media storage class is used. The "cloudinary_storage" app is deliberately NOT installed:
    # it replaces collectstatic with its own version, which breaks WhiteNoise on newer Django.
    INSTALLED_APPS.append("cloudinary")
    STORAGES["default"] = {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"}
    # django-cloudinary-storage still reads these two old setting names, which Django 5.1+ no
    # longer defines. Providing them (same values as STORAGES above) avoids an AttributeError.
    STATICFILES_STORAGE = STORAGES["staticfiles"]["BACKEND"]
    DEFAULT_FILE_STORAGE = STORAGES["default"]["BACKEND"]

# Uploads
MAX_IMAGE_UPLOAD_MB = int(os.environ.get("MAX_IMAGE_UPLOAD_MB", "5"))
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Tradewind <no-reply@example.com>")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "support@example.com")

# --------------------------------------------------------------------------
# Marketplace settings
# --------------------------------------------------------------------------
SITE_NAME = os.environ.get("SITE_NAME", "Tradewind")
CURRENCY_CODE = os.environ.get("CURRENCY_CODE", "NGN")
CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "₦")
PRODUCTS_PER_PAGE = 12
MAX_GALLERY_IMAGES = 6
MAX_CART_ITEM_QUANTITY = 99

# "test" is the built-in, clearly labelled test-payment workflow.
# "test" = simulated payments (no money). "paystack" = real payments through Paystack.
PAYMENT_GATEWAY = os.environ.get("PAYMENT_GATEWAY", "test").strip().lower()
PAYMENT_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY") or os.environ.get("PAYMENT_PUBLIC_KEY", "")
PAYMENT_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY") or os.environ.get("PAYMENT_SECRET_KEY", "")
PAYSTACK_BASE_URL = "https://api.paystack.co"
# One Paystack payment can be split between a limited number of sellers.
PAYSTACK_MAX_SELLERS_PER_ORDER = int(os.environ.get("PAYSTACK_MAX_SELLERS_PER_ORDER", "5"))
if PAYMENT_GATEWAY == "paystack" and not PAYMENT_SECRET_KEY and not RUNNING_TESTS:
    raise ImproperlyConfigured("PAYMENT_GATEWAY=paystack needs PAYSTACK_SECRET_KEY to be set.")

# Marketplace commission: this share of every sale goes to the administrator. The payment
# provider's fee is paid out of this share, so sellers always receive (100 - commission)%.
COMMISSION_PERCENT = Decimal(os.environ.get("COMMISSION_PERCENT", "10"))

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "marketplace.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console", "file"], "level": "WARNING", "propagate": False},
        # Important business and administrative actions are logged here.
        "marketplace": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
    },
}
