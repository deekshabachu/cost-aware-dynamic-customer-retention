"""Authentication API tests using an isolated temporary SQLite database."""

from pathlib import Path
import secrets
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import create_access_token, hash_password, verify_password
from api.main import create_app
from database.config import create_database_engine
from database.models import Order, User
from scripts.configure_demo_customer_access import configure_demo_customer_passwords
from scripts.seed_demo_data import DEMO_EMAIL_DOMAIN, seed_demo_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "auth-test.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.auth_secret = secrets.token_urlsafe(48)
        self.app = create_app(
            database_engine=self.engine,
            inference_service=object(),
            auth_secret_key=self.auth_secret,
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.engine.dispose()
        self.temp_directory.cleanup()

    @staticmethod
    def registration_payload(email: str = "new.customer@example.test") -> dict[str, str]:
        return {
            "name": "New Customer",
            "email": email,
            "password": "A-long-demo-passphrase-2026",
        }

    def register_customer(self, email: str = "new.customer@example.test") -> dict[str, object]:
        response = self.client.post("/auth/register", json=self.registration_payload(email))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_registration_hashes_password_and_returns_only_safe_fields(self) -> None:
        response = self.client.post("/auth/register", json=self.registration_payload())

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(set(body), {"id", "email"})
        self.assertNotIn("password", response.text.lower())
        self.assertNotIn("password_hash", response.text.lower())
        with Session(self.engine) as session:
            user = session.get(User, body["id"])
            self.assertIsNotNone(user)
            self.assertTrue(user.password_hash.startswith("scrypt$16384$8$1$"))
            self.assertNotEqual(user.password_hash, self.registration_payload()["password"])
            self.assertTrue(verify_password(self.registration_payload()["password"], user.password_hash))

    def test_duplicate_email_is_rejected_case_insensitively(self) -> None:
        self.register_customer()

        duplicate = self.client.post(
            "/auth/register", json=self.registration_payload("NEW.CUSTOMER@EXAMPLE.TEST")
        )

        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("already exists", duplicate.json()["detail"])

    def test_valid_login_and_current_user_endpoint(self) -> None:
        created = self.register_customer()
        login = self.client.post(
            "/auth/login",
            json={"email": created["email"], "password": self.registration_payload()["password"]},
        )

        self.assertEqual(login.status_code, 200, login.text)
        body = login.json()
        self.assertEqual(body["token_type"], "bearer")
        self.assertEqual(body["expires_in"], 3600)
        self.assertEqual(body["user"], created)
        self.assertNotIn("password_hash", login.text)

        current = self.client.get(
            "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json(), created)

    def test_login_rejects_unknown_email_and_wrong_password(self) -> None:
        created = self.register_customer()
        wrong_password = self.client.post(
            "/auth/login", json={"email": created["email"], "password": "incorrect-password"}
        )
        unknown_email = self.client.post(
            "/auth/login", json={"email": "missing@example.test", "password": "incorrect-password"}
        )

        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(unknown_email.status_code, 401)
        self.assertEqual(wrong_password.json()["detail"], unknown_email.json()["detail"])

    def test_current_user_rejects_missing_invalid_and_expired_tokens(self) -> None:
        created = self.register_customer()
        expired = create_access_token(int(created["id"]), self.auth_secret, expires_in_seconds=-1)
        valid_token = create_access_token(int(created["id"]), self.auth_secret)
        encoded, signature = valid_token.split(".")
        changed_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
        tampered = f"{encoded}.{changed_signature}"
        for headers in (
            {},
            {"Authorization": "Bearer not-a-signed-token"},
            {"Authorization": f"Bearer {expired}"},
            {"Authorization": f"Bearer {tampered}"},
        ):
            with self.subTest(headers=headers):
                response = self.client.get("/auth/me", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertIn("WWW-Authenticate", response.headers)

    def test_cors_allows_the_local_vite_origin_only(self) -> None:
        allowed = self.client.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        allowed_admin_update = self.client.options(
            "/admin/budget",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        rejected = self.client.options(
            "/auth/login",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:5173")
        self.assertEqual(allowed_admin_update.status_code, 200)
        self.assertIn("PUT", allowed_admin_update.headers.get("access-control-allow-methods", ""))
        self.assertNotIn("access-control-allow-origin", rejected.headers)

    def test_short_password_and_invalid_email_are_rejected(self) -> None:
        short_password = self.registration_payload()
        short_password["password"] = "abc"
        invalid_email = self.registration_payload("not-an-email")

        self.assertEqual(self.client.post("/auth/register", json=short_password).status_code, 422)
        self.assertEqual(self.client.post("/auth/register", json=invalid_email).status_code, 422)

    def test_four_character_customer_password_can_register_and_login(self) -> None:
        payload = self.registration_payload("short.password@example.test")
        payload["password"] = "Ab4!"
        registration = self.client.post("/auth/register", json=payload)
        self.assertEqual(registration.status_code, 201, registration.text)

        login = self.client.post(
            "/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        self.assertEqual(login.status_code, 200, login.text)

        too_short_login = self.client.post(
            "/auth/login", json={"email": payload["email"], "password": "abc"}
        )
        self.assertEqual(too_short_login.status_code, 422)

        invalid_four_character_login = self.client.post(
            "/auth/login", json={"email": payload["email"], "password": "Nope"}
        )
        self.assertEqual(invalid_four_character_login.status_code, 401)

    def test_seeded_demo_accounts_and_unrelated_records_remain_usable_and_unchanged(self) -> None:
        with Session(self.engine) as session:
            unrelated = User(
                name="Unrelated Account",
                email="unrelated@example.test",
                password_hash=hash_password("Unrelated-account-passphrase"),
                role="customer",
            )
            session.add(unrelated)
            session.commit()
            unrelated_id = unrelated.id
            unrelated_hash = unrelated.password_hash

        seeded = seed_demo_data(self.engine)
        self.assertEqual(len(seeded), 9)
        demo_email = f"customer01@{DEMO_EMAIL_DOMAIN}"
        test_only_password = "TestOnly-Customer-01-Password!"
        configure_demo_customer_passwords(
            self.engine, {demo_email: test_only_password}
        )
        demo_login = self.client.post(
            "/auth/login", json={"email": demo_email, "password": test_only_password}
        )
        self.assertEqual(demo_login.status_code, 200, demo_login.text)

        with Session(self.engine) as session:
            saved_unrelated = session.get(User, unrelated_id)
            self.assertEqual(saved_unrelated.email, "unrelated@example.test")
            self.assertEqual(saved_unrelated.password_hash, unrelated_hash)
            self.assertEqual(
                session.scalar(select(User.id).where(User.email == demo_email)),
                next(user_id for user_id, email in seeded if email == demo_email),
            )
            self.assertEqual(session.query(Order).count(), 14)


if __name__ == "__main__":
    unittest.main()
