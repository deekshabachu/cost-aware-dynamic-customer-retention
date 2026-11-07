"""Tests for the explicitly invoked local faculty-demo credential setup."""

import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import verify_password
from api.main import create_app
from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import CustomerActivity, Order, RetentionIntervention, RetentionPrediction, User
from scripts.configure_local_demo import (
    LOCAL_ADMIN_EMAIL,
    LOCAL_CUSTOMER_PASSWORDS,
    configure_local_demo_credentials,
)
from scripts.seed_demo_data import DEMO_MANIFEST_EVENT_TYPE, seed_demo_data
from tests.test_admin_api import FakeInferenceService


class LocalDemoSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.database_path = root / "local-demo.db"
        self.env_path = root / ".env.local"
        self.engine = create_database_engine(f"sqlite:///{self.database_path.as_posix()}")
        initialize_database(self.engine)
        seed_demo_data(self.engine)
        self.passwords = {
            LOCAL_ADMIN_EMAIL: "TestOnly-Local-Admin-Password!",
            "customer01@demo.customer-retention.local": "TestOnly-Customer-01-Password!",
            "customer02@demo.customer-retention.local": "TestOnly-Customer-02-Password!",
        }

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_directory.cleanup()

    def _preserved_record_counts(self) -> tuple[int, int, int, int]:
        with Session(self.engine) as session:
            return (
                session.scalar(select(func.count()).select_from(Order)),
                session.scalar(select(func.count()).select_from(CustomerActivity)),
                session.scalar(select(func.count()).select_from(RetentionPrediction)),
                session.scalar(select(func.count()).select_from(RetentionIntervention)),
            )

    def test_setup_writes_hashes_and_changes_only_two_seeded_customers(self) -> None:
        before_counts = self._preserved_record_counts()
        with Session(self.engine) as session:
            before_users = {
                user.email: (user.id, user.role, user.password_hash)
                for user in session.scalars(select(User)).all()
            }

        configure_local_demo_credentials(
            self.engine, self.passwords, env_path=self.env_path
        )

        contents = self.env_path.read_text(encoding="utf-8")
        settings = dict(line.split("=", 1) for line in contents.splitlines())
        self.assertEqual(settings["ADMIN_EMAIL"], LOCAL_ADMIN_EMAIL)
        self.assertTrue(settings["ADMIN_PASSWORD_HASH"].startswith("scrypt$16384$8$1$"))
        self.assertRegex(settings["AUTH_SECRET_KEY"], r"^[A-Za-z0-9_-]{64}$")
        for password in self.passwords.values():
            self.assertNotIn(password, contents)
        self.assertTrue(verify_password(self.passwords[LOCAL_ADMIN_EMAIL], settings["ADMIN_PASSWORD_HASH"]))

        with Session(self.engine) as session:
            after_users = {
                user.email: (user.id, user.role, user.password_hash)
                for user in session.scalars(select(User)).all()
            }
        self.assertEqual(set(before_users), set(after_users))
        for email in LOCAL_CUSTOMER_PASSWORDS:
            old_id, old_role, old_hash = before_users[email]
            new_id, new_role, new_hash = after_users[email]
            self.assertEqual((old_id, old_role), (new_id, new_role))
            self.assertNotEqual(old_hash, new_hash)
            self.assertTrue(verify_password(self.passwords[email], new_hash))
        for email in set(before_users) - set(LOCAL_CUSTOMER_PASSWORDS):
            self.assertEqual(before_users[email], after_users[email])
        self.assertEqual(before_counts, self._preserved_record_counts())

    def test_setup_preserves_existing_auth_secret_on_repeat(self) -> None:
        self.env_path.write_text(
            "ADMIN_EMAIL=admin@littleleaf.local\n"
            "ADMIN_PASSWORD_HASH=placeholder\n"
            "AUTH_SECRET_KEY=" + secrets.token_urlsafe(48) + "\n",
            encoding="utf-8",
        )
        old_secret = self.env_path.read_text(encoding="utf-8").split("AUTH_SECRET_KEY=", 1)[1].strip()
        configure_local_demo_credentials(self.engine, self.passwords, env_path=self.env_path)
        saved = dict(line.split("=", 1) for line in self.env_path.read_text(encoding="utf-8").splitlines())
        self.assertEqual(saved["AUTH_SECRET_KEY"], old_secret)

    def test_setup_replaces_only_an_invalid_existing_auth_secret(self) -> None:
        self.env_path.write_text(
            "ADMIN_EMAIL=admin@littleleaf.local\n"
            "ADMIN_PASSWORD_HASH=placeholder\n"
            "AUTH_SECRET_KEY=too-short\n",
            encoding="utf-8",
        )
        configure_local_demo_credentials(self.engine, self.passwords, env_path=self.env_path)
        saved = dict(line.split("=", 1) for line in self.env_path.read_text(encoding="utf-8").splitlines())
        self.assertRegex(saved["AUTH_SECRET_KEY"], r"^[A-Za-z0-9_-]{64}$")
        self.assertNotEqual(saved["AUTH_SECRET_KEY"], "too-short")

    def test_generated_credentials_authenticate_admin_and_keep_customers_out_of_admin(self) -> None:
        short_passwords = {
            LOCAL_ADMIN_EMAIL: "Adm4",
            "customer01@demo.customer-retention.local": "Cst1",
            "customer02@demo.customer-retention.local": "Cst2",
        }
        configure_local_demo_credentials(self.engine, short_passwords, env_path=self.env_path)
        settings = dict(line.split("=", 1) for line in self.env_path.read_text(encoding="utf-8").splitlines())
        app = create_app(
            database_engine=self.engine,
            inference_service=FakeInferenceService(),
            auth_secret_key=settings["AUTH_SECRET_KEY"],
            admin_email=settings["ADMIN_EMAIL"],
            admin_password_hash=settings["ADMIN_PASSWORD_HASH"],
        )
        with TestClient(app) as client:
            login = client.post("/admin/auth/login", json={
                "email": LOCAL_ADMIN_EMAIL,
                "password": short_passwords[LOCAL_ADMIN_EMAIL],
            })
            self.assertEqual(login.status_code, 200)
            admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            self.assertEqual(client.get("/admin/dashboard", headers=admin_headers).status_code, 200)

            bad_login = client.post("/admin/auth/login", json={
                "email": LOCAL_ADMIN_EMAIL,
                "password": "Wrong-Local-Admin-Password!",
            })
            self.assertEqual(bad_login.status_code, 401)

            customer_login = client.post("/auth/login", json={
                "email": "customer01@demo.customer-retention.local",
                "password": short_passwords["customer01@demo.customer-retention.local"],
            })
            self.assertEqual(customer_login.status_code, 200)
            customer_headers = {"Authorization": f"Bearer {customer_login.json()['access_token']}"}
            self.assertEqual(client.get("/admin/dashboard", headers=customer_headers).status_code, 401)

            customer02_login = client.post("/auth/login", json={
                "email": "customer02@demo.customer-retention.local",
                "password": short_passwords["customer02@demo.customer-retention.local"],
            })
            self.assertEqual(customer02_login.status_code, 200)
            customer02_headers = {"Authorization": f"Bearer {customer02_login.json()['access_token']}"}
            self.assertEqual(client.get("/admin/dashboard", headers=customer02_headers).status_code, 401)

    def test_passwords_must_be_distinct_and_invalid_passwords_do_not_change_users(self) -> None:
        before = self._preserved_record_counts()
        invalid = dict(self.passwords)
        invalid["customer01@demo.customer-retention.local"] = invalid[LOCAL_ADMIN_EMAIL]
        with self.assertRaisesRegex(ValueError, "different password"):
            configure_local_demo_credentials(self.engine, invalid, env_path=self.env_path)
        self.assertFalse(self.env_path.exists())
        self.assertEqual(before, self._preserved_record_counts())

    def test_four_character_local_demo_passwords_are_accepted(self) -> None:
        short_passwords = {
            LOCAL_ADMIN_EMAIL: "Adm4",
            "customer01@demo.customer-retention.local": "Cst1",
            "customer02@demo.customer-retention.local": "Cst2",
        }
        configure_local_demo_credentials(
            self.engine, short_passwords, env_path=self.env_path
        )
        settings = dict(
            line.split("=", 1)
            for line in self.env_path.read_text(encoding="utf-8").splitlines()
        )
        self.assertTrue(verify_password("Adm4", settings["ADMIN_PASSWORD_HASH"]))
        with Session(self.engine) as session:
            for email, password in short_passwords.items():
                if email == LOCAL_ADMIN_EMAIL:
                    continue
                user = session.scalar(select(User).where(User.email == email))
                self.assertTrue(verify_password(password, user.password_hash))

    def test_three_character_demo_password_is_rejected_before_updates(self) -> None:
        before = self._preserved_record_counts()
        invalid = dict(self.passwords)
        invalid[LOCAL_ADMIN_EMAIL] = "Adm"
        with self.assertRaisesRegex(ValueError, "4 to 128 characters"):
            configure_local_demo_credentials(
                self.engine, invalid, env_path=self.env_path
            )
        self.assertFalse(self.env_path.exists())
        self.assertEqual(before, self._preserved_record_counts())


if __name__ == "__main__":
    unittest.main()
