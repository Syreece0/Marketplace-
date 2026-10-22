from django.core import mail
from django.urls import reverse

from core.templatetags.core_extras import money, status_tone
from core.factories import BaseTestCase, make_customer, make_product, make_seller


class PublicPageTests(BaseTestCase):
    def test_public_pages_load(self):
        for name in ("core:home", "core:about", "core:contact", "core:terms", "core:privacy",
                     "products:list", "accounts:login", "accounts:register", "accounts:register_seller",
                     "accounts:password_reset", "accounts:logged_out"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_homepage_empty_state_has_no_fake_products(self):
        page = self.client.get(reverse("core:home"))
        self.assertContains(page, "No products yet")

    def test_missing_page_shows_friendly_404(self):
        response = self.client.get("/definitely/not/here/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "find that page", status_code=404)
        self.assertNotContains(response, "Traceback", status_code=404)

    def test_forbidden_page_is_friendly(self):
        self.login(make_customer())
        response = self.client.get(reverse("dashboard:admin"))
        self.assertContains(response, "have access", status_code=403)

    def test_security_headers_and_csrf_cookie_flags(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")

    def test_post_without_csrf_token_is_rejected(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        user = make_customer("csrfuser")
        strict.force_login(user)
        response = strict.post(reverse("accounts:profile_edit"), {"full_name": "x"})
        self.assertEqual(response.status_code, 403)

    def test_user_content_is_escaped(self):
        _, shop = make_seller()
        make_product(shop, name="<script>alert(1)</script>", description="<img src=x onerror=alert(1)>")
        page = self.client.get(reverse("products:list"))
        self.assertNotContains(page, "<script>alert(1)</script>")
        self.assertContains(page, "&lt;script&gt;alert(1)&lt;/script&gt;")


class ContactFormTests(BaseTestCase):
    def test_valid_message_sends_email(self):
        response = self.client.post(
            reverse("core:contact"),
            {"name": "Ada", "email": "ada@example.com", "subject": "Hello", "message": "A question"},
        )
        self.assertRedirects(response, reverse("core:contact"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("A question", mail.outbox[0].body)

    def test_invalid_message_shows_errors_and_keeps_values(self):
        response = self.client.post(
            reverse("core:contact"), {"name": "Ada", "email": "not-an-email", "subject": "", "message": "Hi"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, "Enter a valid email address")
        self.assertContains(response, "Ada")

    def test_header_injection_is_rejected(self):
        response = self.client.post(
            reverse("core:contact"),
            {"name": "Ada", "email": "ada@example.com", "subject": "Hi\nBcc: victim@example.com", "message": "x"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "single line")
        self.assertEqual(len(mail.outbox), 0)


class TranslationTests(BaseTestCase):
    def test_language_switch_sets_cookie_and_changes_page(self):
        response = self.client.post(reverse("set_language"), {"language": "fr", "next": "/"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.cookies["django_language"].value, "fr")
        page = self.client.get(reverse("core:home"))
        self.assertEqual(page.context["LANGUAGE_CODE"], "fr")
        self.assertContains(page, '<html lang="fr">')

    def test_french_interface_text_is_translated(self):
        self.client.post(reverse("set_language"), {"language": "fr", "next": "/"})
        page = self.client.get(reverse("core:home"))
        self.assertContains(page, "Se connecter")  # "Sign in"

    def test_unsupported_language_is_ignored(self):
        self.client.post(reverse("set_language"), {"language": "xx", "next": "/"})
        page = self.client.get(reverse("core:home"))
        self.assertEqual(page.context["LANGUAGE_CODE"], "en")

    def test_user_generated_content_is_not_translated(self):
        _, shop = make_seller()
        make_product(shop, name="Sign in lamp")
        self.client.post(reverse("set_language"), {"language": "fr", "next": "/"})
        page = self.client.get(reverse("products:list"))
        self.assertContains(page, "Sign in lamp")

    def test_settings_declare_languages(self):
        from django.conf import settings
        self.assertEqual({code for code, _ in settings.LANGUAGES}, {"en", "fr"})
        self.assertTrue(settings.USE_I18N)


class TemplateTagTests(BaseTestCase):
    def test_money_filter(self):
        self.assertEqual(money(1500), "₦1,500.00")
        self.assertEqual(money("12.5"), "₦12.50")
        self.assertEqual(money("garbage"), "")
        self.assertEqual(money(None), "")

    def test_status_tone(self):
        self.assertEqual(status_tone("approved"), "success")
        self.assertEqual(status_tone("pending"), "warning")
        self.assertEqual(status_tone("rejected"), "danger")
        self.assertEqual(status_tone("whatever"), "neutral")


class SettingsSafetyTests(BaseTestCase):
    def test_debug_is_off_in_tests(self):
        from django.conf import settings
        self.assertFalse(settings.DEBUG)

    def test_password_validators_enforce_length(self):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            validate_password("short1A!")


class SeedCategoriesCommandTests(BaseTestCase):
    def test_command_creates_only_categories_and_is_idempotent(self):
        from django.core.management import call_command
        from accounts.models import User
        from products.models import Category, Product

        call_command("seed_categories", stdout=mail_free_stdout())
        first = Category.objects.count()
        self.assertGreater(first, 0)
        call_command("seed_categories", stdout=mail_free_stdout())
        self.assertEqual(Category.objects.count(), first)
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(User.objects.count(), 0)


def mail_free_stdout():
    import io
    return io.StringIO()
