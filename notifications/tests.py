from django.urls import reverse

from core.factories import BaseTestCase, make_customer, make_seller
from notifications.models import Notification
from notifications.services import notify


class NotificationTests(BaseTestCase):
    def setUp(self):
        self.alice = make_customer("alice")
        self.bob = make_customer("bob")

    def test_users_only_see_their_own_notifications(self):
        notify(self.alice, "Alice's secret update")
        notify(self.bob, "Bob's private update")
        self.login(self.alice)
        page = self.client.get(reverse("notifications:list"))
        self.assertContains(page, "Alice&#x27;s secret update")
        self.assertNotContains(page, "Bob")

    def test_cannot_mark_another_users_notification(self):
        bobs = notify(self.bob, "For Bob")
        self.login(self.alice)
        response = self.client.post(reverse("notifications:mark_read", args=[bobs.pk]))
        self.assertEqual(response.status_code, 404)
        bobs.refresh_from_db()
        self.assertFalse(bobs.is_read)

    def test_mark_read_and_mark_all_read(self):
        first = notify(self.alice, "one")
        notify(self.alice, "two")
        bobs = notify(self.bob, "bobs")
        self.login(self.alice)
        self.client.post(reverse("notifications:mark_read", args=[first.pk]))
        first.refresh_from_db()
        self.assertTrue(first.is_read)
        self.client.post(reverse("notifications:mark_all_read"))
        self.assertFalse(Notification.objects.filter(user=self.alice, is_read=False).exists())
        bobs.refresh_from_db()
        self.assertFalse(bobs.is_read)

    def test_unread_count_endpoint(self):
        notify(self.alice, "one")
        notify(self.alice, "two")
        notify(self.bob, "not counted")
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse("notifications:unread_count")).json(), {"count": 2})

    def test_login_required(self):
        for name in ("notifications:list", "notifications:unread_count"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_mark_read_requires_post(self):
        item = notify(self.alice, "one")
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse("notifications:mark_read", args=[item.pk])).status_code, 405)

    def test_external_urls_are_dropped(self):
        item = notify(self.alice, "link", "https://evil.example/")
        self.assertEqual(item.url, "")
        item = notify(self.alice, "link", "/orders/1/")
        self.assertEqual(item.url, "/orders/1/")

    def test_empty_state_and_navbar_badge(self):
        user, _ = make_seller()
        self.login(user)
        self.assertContains(self.client.get(reverse("notifications:list")), "No notifications")
        notify(user, "ping")
        page = self.client.get(reverse("notifications:list"))
        self.assertEqual(page.context["unread_notifications"], 1)
