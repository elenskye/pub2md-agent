"""Auth flow and single-active-session enforcement."""

from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase


def make_user(name="guest1", password="pw-123456"):
    return User.objects.create_user(username=name, password=password)


class LoginTests(TestCase):
    def setUp(self):
        make_user()

    def test_login_success_json_body(self):
        resp = self.client.post(
            "/api/login",
            data='{"username": "guest1", "password": "pw-123456"}',
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["username"], "guest1")

    def test_login_success_form_body(self):
        resp = self.client.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        self.assertEqual(resp.status_code, 200)

    def test_bad_credentials_rejected(self):
        resp = self.client.post("/api/login", {"username": "guest1", "password": "nope"})
        self.assertEqual(resp.status_code, 401)

    def test_me_requires_login(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.client.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        resp = self.client.get("/api/me")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["username"], "guest1")

    def test_logout_ends_session(self):
        self.client.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/me").status_code, 401)


class SingleActiveSessionTests(TestCase):
    def setUp(self):
        make_user()

    def test_second_login_kicks_first_device(self):
        device_a, device_b = Client(), Client()
        device_a.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        self.assertEqual(device_a.get("/api/me").status_code, 200)

        device_b.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        self.assertEqual(device_b.get("/api/me").status_code, 200)
        # Device A's session row was deleted → it is anonymous now.
        self.assertEqual(device_a.get("/api/me").status_code, 401)

    def test_relogin_same_device_keeps_working(self):
        self.client.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        self.client.post("/api/login", {"username": "guest1", "password": "pw-123456"})
        self.assertEqual(self.client.get("/api/me").status_code, 200)


class JobsApiRequiresAuthTests(TestCase):
    def test_all_job_endpoints_reject_anonymous(self):
        self.assertEqual(self.client.get("/api/styles").status_code, 401)
        self.assertEqual(self.client.post("/api/jobs").status_code, 401)
        self.assertEqual(
            self.client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code, 401
        )
        self.assertEqual(
            self.client.get(
                "/api/jobs/00000000-0000-0000-0000-000000000000/download"
            ).status_code,
            401,
        )


class RotateAccountsTests(TestCase):
    def test_rotation_creates_accounts_and_new_credentials_work(self):
        out = StringIO()
        call_command("rotate_accounts", stdout=out)
        lines = [l for l in out.getvalue().splitlines() if ": " in l]
        self.assertEqual(len(lines), 2)
        name, password = lines[0].split(": ")
        resp = self.client.post("/api/login", {"username": name, "password": password})
        self.assertEqual(resp.status_code, 200)

    def test_rotation_kills_live_sessions(self):
        out = StringIO()
        call_command("rotate_accounts", stdout=out)
        name, password = [l for l in out.getvalue().splitlines() if ": " in l][0].split(": ")
        self.client.post("/api/login", {"username": name, "password": password})
        self.assertEqual(self.client.get("/api/me").status_code, 200)

        call_command("rotate_accounts", stdout=StringIO())
        self.assertEqual(self.client.get("/api/me").status_code, 401)
