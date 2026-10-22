import re

from django.core import mail
from django.urls import reverse

from accounts.models import Role, SellerStatus, User
from core.factories import PASSWORD, BaseTestCase, make_admin, make_customer, make_seller


class RegistrationTests(BaseTestCase):
    def test_customer_registration_creates_customer_and_logs_in(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "newbuyer", "email": "Buyer@Example.com", "full_name": "New Buyer",
                "phone_number": "0800000000", "password1": PASSWORD, "password2": PASSWORD,
            },
        )
        self.assertRedirects(response, reverse("dashboard:home"), fetch_redirect_response=False)
        user = User.objects.get(username="newbuyer")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertEqual(user.email, "buyer@example.com")  # normalised
        self.assertEqual(user.profile.full_name, "New Buyer")
        self.assertIn("_auth_user_id", self.client.session)

    def test_seller_registration_creates_pending_shop(self):
        self.client.post(
            reverse("accounts:register_seller"),
            {
                "username": "newseller", "email": "s@example.com", "full_name": "Sam Seller",
                "password1": PASSWORD, "password2": PASSWORD, "shop_name": "Sam's Store",
                "shop_description": "Things",
            },
        )
        user = User.objects.get(username="newseller")
        self.assertEqual(user.role, Role.SELLER)
        self.assertEqual(user.seller_profile.status, SellerStatus.PENDING)
        self.assertFalse(user.is_approved_seller)

    def test_registration_cannot_choose_role(self):
        self.client.post(
            reverse("accounts:register"),
            {
                "username": "sneaky", "email": "sneaky@example.com", "full_name": "Sneaky",
                "password1": PASSWORD, "password2": PASSWORD, "role": "admin", "is_staff": "on",
                "is_superuser": "on",
            },
        )
        user = User.objects.get(username="sneaky")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_duplicate_email_and_shop_name_rejected(self):
        make_customer("existing")
        response = self.client.post(
            reverse("accounts:register"),
            {"username": "other", "email": "existing@example.com", "full_name": "X",
             "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertFalse(User.objects.filter(username="other").exists())

        make_seller("first", shop_name="Unique Shop")
        response = self.client.post(
            reverse("accounts:register_seller"),
            {"username": "second", "email": "second@example.com", "full_name": "S",
             "password1": PASSWORD, "password2": PASSWORD, "shop_name": "unique shop"},
        )
        self.assertContains(response, "already taken")

    def test_weak_password_rejected_and_values_preserved(self):
        response = self.client.post(
            reverse("accounts:register"),
            {"username": "weakling", "email": "w@example.com", "full_name": "Weak Person",
             "password1": "12345678", "password2": "12345678"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="weakling").exists())
        self.assertContains(response, "weakling")  # form values are preserved
        self.assertContains(response, "Weak Person")


class LoginLogoutTests(BaseTestCase):
    def setUp(self):
        self.customer = make_customer("alice")

    def test_login_with_username_and_email(self):
        for identifier in ("alice", "alice@example.com", "ALICE@example.com"):
            self.client.logout()
            response = self.client.post(
                reverse("accounts:login"), {"username": identifier, "password": PASSWORD}
            )
            self.assertEqual(response.status_code, 302, identifier)
            self.assertIn("_auth_user_id", self.client.session)

    def test_invalid_credentials(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "alice", "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Please enter a correct")

    def test_deactivated_user_cannot_login(self):
        self.customer.is_active = False
        self.customer.save()
        response = self.client.post(
            reverse("accounts:login"), {"username": "alice", "password": PASSWORD}
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 200)

    def test_logout_requires_post(self):
        self.login(self.customer)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:logged_out"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_next_parameter_must_be_local(self):
        response = self.client.post(
            reverse("accounts:login") + "?next=https://evil.example/",
            {"username": "alice", "password": PASSWORD, "next": "https://evil.example/"},
        )
        self.assertNotIn("evil.example", response.headers.get("Location", ""))


class RoleRedirectTests(BaseTestCase):
    def test_dashboard_home_redirects_by_role(self):
        customer = make_customer("c1")
        seller, _ = make_seller("s1")
        admin = make_admin("a1")
        expectations = [
            (customer, "dashboard:customer"),
            (seller, "dashboard:seller"),
            (admin, "dashboard:admin"),
        ]
        for user, target in expectations:
            self.client.logout()
            self.login(user)
            response = self.client.get(reverse("dashboard:home"))
            self.assertRedirects(response, reverse(target), fetch_redirect_response=False)

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_superuser_created_by_manager_is_admin_role(self):
        user = User.objects.create_superuser("root", "root@example.com", PASSWORD)
        self.assertEqual(user.role, Role.ADMIN)
        self.assertTrue(user.is_marketplace_admin)
        self.assertTrue(hasattr(user, "profile"))


class PasswordResetTests(BaseTestCase):
    def test_full_reset_flow(self):
        user = make_customer("resetme")
        response = self.client.post(reverse("accounts:password_reset"), {"email": user.email})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        link = re.search(r"http://testserver(/accounts/reset/\S+)", mail.outbox[0].body).group(1)
        response = self.client.get(link)
        self.assertEqual(response.status_code, 302)  # Django swaps the token into the session
        new_password = "An0ther-Strong-Pass!77"
        response = self.client.post(
            response.url, {"new_password1": new_password, "new_password2": new_password}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))

    def test_unknown_email_gives_same_response_and_sends_nothing(self):
        response = self.client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_change_requires_login_and_works(self):
        self.assertEqual(self.client.get(reverse("accounts:password_change")).status_code, 302)
        user = self.login(make_customer("changer"))
        new_password = "Brand-New-Pass!99"
        response = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": PASSWORD, "new_password1": new_password, "new_password2": new_password},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))


class PermissionTests(BaseTestCase):
    def test_customer_cannot_access_seller_or_admin_pages(self):
        self.login(make_customer())
        for name in ("dashboard:seller", "products:seller_list", "products:create",
                     "requests_app:seller_list", "orders:seller_list", "accounts:shop_settings",
                     "dashboard:admin", "dashboard:users", "dashboard:sellers", "dashboard:products",
                     "dashboard:categories", "dashboard:reports", "dashboard:statistics"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_seller_cannot_access_admin_or_customer_pages(self):
        user, _ = make_seller()
        self.login(user)
        for name in ("dashboard:admin", "dashboard:users", "dashboard:sellers", "dashboard:orders",
                     "wishlist:list", "orders:cart", "orders:list", "requests_app:customer_list"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_staff_flag_alone_does_not_grant_admin_access(self):
        staff = make_customer("staffer", is_staff=True)
        self.login(staff)
        self.assertEqual(self.client.get(reverse("dashboard:admin")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:users")).status_code, 403)

    def test_admin_can_access_admin_pages(self):
        self.login(make_admin())
        for name in ("dashboard:admin", "dashboard:users", "dashboard:sellers", "dashboard:products",
                     "dashboard:categories", "dashboard:requests", "dashboard:orders",
                     "dashboard:reports", "dashboard:reviews", "dashboard:statistics"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_pending_seller_is_redirected_from_product_tools(self):
        user, _ = make_seller("pending", status=SellerStatus.PENDING)
        self.login(user)
        response = self.client.get(reverse("products:create"))
        self.assertRedirects(response, reverse("dashboard:seller"), fetch_redirect_response=False)
        page = self.client.get(reverse("dashboard:seller"))
        self.assertContains(page, "waiting for approval")

    def test_seller_cannot_edit_own_approval_status_via_shop_settings(self):
        user, profile = make_seller("tricky", status=SellerStatus.PENDING)
        self.login(user)
        self.client.post(
            reverse("accounts:shop_settings"),
            {"shop_name": "Tricky Shop", "status": "approved", "description": "x"},
        )
        profile.refresh_from_db()
        self.assertEqual(profile.status, SellerStatus.PENDING)


class ProfileTests(BaseTestCase):
    def test_profile_edit_saves_changes(self):
        user = self.login(make_customer())
        response = self.client.post(
            reverse("accounts:profile_edit"),
            {"full_name": "Updated Name", "phone_number": "123", "location": "Lagos"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.full_name, "Updated Name")

    def test_shop_settings_save(self):
        user, profile = make_seller()
        self.login(user)
        response = self.client.post(
            reverse("accounts:shop_settings"),
            {"shop_name": "Renamed Shop", "description": "New description"},
        )
        self.assertRedirects(response, reverse("accounts:shop_settings"))
        profile.refresh_from_db()
        self.assertEqual(profile.shop_name, "Renamed Shop")
        self.assertEqual(profile.status, SellerStatus.APPROVED)
