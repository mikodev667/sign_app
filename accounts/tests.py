from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AdmissionAuthPageTests(TestCase):
    def test_admission_login_page_is_white_label(self):
        response = self.client.get(reverse("accounts:admission_login"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "QolQoyu")
        self.assertContains(response, reverse("accounts:admission_register"))

    def test_admission_register_page_is_white_label(self):
        response = self.client.get(reverse("accounts:admission_register"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "QolQoyu")
        self.assertContains(response, reverse("accounts:admission_login"))

    def test_admission_login_redirects_to_admissions_dashboard(self):
        get_user_model().objects.create_user(username="vice", password="StrongPass123")

        response = self.client.post(reverse("accounts:admission_login"), {
            "username": "vice",
            "password": "StrongPass123",
        })

        self.assertRedirects(
            response,
            reverse("admissions:dashboard"),
            fetch_redirect_response=False,
        )

    def test_vice_rector_dashboard_uses_admission_login_for_anonymous_user(self):
        response = self.client.get(reverse("admissions:vice_rector_dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:admission_login"), response["Location"])
