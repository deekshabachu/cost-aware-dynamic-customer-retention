"""Safety tests for explicitly configured local demo account passwords."""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import verify_password
from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import CustomerActivity, User
from scripts.configure_demo_customer_access import (
    DEMO_CUSTOMER_02,
    DEMO_ACCESS_ACCOUNTS,
    configure_generated_customer_02_access,
    configure_demo_customer_passwords,
)
from scripts.seed_demo_data import DEMO_MANIFEST_EVENT_TYPE, seed_demo_data


PASSWORDS = {
    "customer01@demo.customer-retention.local": "TestOnly-Demo-Account-01!",
    "customer03@demo.customer-retention.local": "TestOnly-Demo-Account-03!",
}


class DemoCustomerAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "demo-access-test.db"
        self.engine = create_database_engine(f"sqlite:///{path.as_posix()}")
        initialize_database(self.engine)
        seed_demo_data(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_directory.cleanup()

    def test_updates_only_two_seeded_accounts_using_existing_hash_format(self) -> None:
        with Session(self.engine) as session:
            before = {
                user.email: user.password_hash
                for user in session.scalars(select(User)).all()
            }
            unrelated = User(
                name="Unrelated Customer",
                email="unrelated@example.test",
                password_hash="unrelated-original-hash",
                role="customer",
            )
            session.add(unrelated)
            session.commit()

        configure_demo_customer_passwords(self.engine, PASSWORDS)

        with Session(self.engine) as session:
            saved = {user.email: user for user in session.scalars(select(User)).all()}
            for email, password in PASSWORDS.items():
                self.assertTrue(saved[email].password_hash.startswith("scrypt$16384$8$1$"))
                self.assertNotEqual(saved[email].password_hash, password)
                self.assertTrue(verify_password(password, saved[email].password_hash))
            for email, password_hash in before.items():
                if email not in DEMO_ACCESS_ACCOUNTS:
                    self.assertEqual(saved[email].password_hash, password_hash)
            self.assertEqual(saved["unrelated@example.test"].password_hash, "unrelated-original-hash")

    def test_invalid_demo_marker_prevents_both_password_updates(self) -> None:
        with Session(self.engine) as session:
            original_hash = session.scalar(
                select(User.password_hash).where(User.email == next(iter(DEMO_ACCESS_ACCOUNTS)))
            )
            second_customer = session.scalar(
                select(User).where(
                    User.email == "customer03@demo.customer-retention.local"
                )
            )
            manifest = session.scalar(
                select(CustomerActivity).where(
                    CustomerActivity.user_id == second_customer.id,
                    CustomerActivity.event_type == DEMO_MANIFEST_EVENT_TYPE,
                )
            )
            manifest.event_metadata = {**manifest.event_metadata, "namespace": "not-the-demo-seeder"}
            session.commit()

        with self.assertRaisesRegex(RuntimeError, "no matching seed marker"):
            configure_demo_customer_passwords(self.engine, PASSWORDS)

        with Session(self.engine) as session:
            saved_hash = session.scalar(
                select(User.password_hash).where(User.email == next(iter(DEMO_ACCESS_ACCOUNTS)))
            )
            self.assertEqual(saved_hash, original_hash)

    def test_requires_exactly_designated_accounts_and_distinct_passwords(self) -> None:
        with self.assertRaisesRegex(ValueError, "only for designated demo accounts"):
            configure_demo_customer_passwords(self.engine, {**PASSWORDS, "other@example.test": "password"})
        same_passwords = {email: "TestOnly-Demo-Shared!" for email in DEMO_ACCESS_ACCOUNTS}
        with self.assertRaisesRegex(ValueError, "distinct password"):
            configure_demo_customer_passwords(self.engine, same_passwords)

    def test_customer02_access_is_generated_without_changing_other_accounts(self) -> None:
        guide_path = Path(self.temp_directory.name) / "demo-access.local.md"
        guide_path.write_text(
            "# Local-only guide\n\nExisting customer credentials remain here.\n",
            encoding="utf-8",
        )
        with Session(self.engine) as session:
            hashes_before = {
                user.email: user.password_hash
                for user in session.scalars(select(User)).all()
            }

        email = configure_generated_customer_02_access(self.engine, guide_path)

        self.assertEqual(email, DEMO_CUSTOMER_02)
        guide = guide_path.read_text(encoding="utf-8")
        self.assertIn("## Customer 02 local access", guide)
        self.assertIn(email, guide)
        password = guide.split("Local password: `", 1)[1].split("`", 1)[0]
        self.assertGreaterEqual(len(password), 24)
        with Session(self.engine) as session:
            saved = {
                user.email: user.password_hash
                for user in session.scalars(select(User)).all()
            }
        self.assertTrue(verify_password(password, saved[email]))
        self.assertNotEqual(saved[email], password)
        for other_email, password_hash in hashes_before.items():
            if other_email != email:
                self.assertEqual(saved[other_email], password_hash)

        with self.assertRaisesRegex(RuntimeError, "already has a local credential entry"):
            configure_generated_customer_02_access(self.engine, guide_path)

    def test_customer02_can_be_configured_independently_with_existing_hashing(self) -> None:
        password = "TestOnly-Demo-Customer-02!"
        configure_demo_customer_passwords(self.engine, {DEMO_CUSTOMER_02: password})
        with Session(self.engine) as session:
            user = session.scalar(select(User).where(User.email == DEMO_CUSTOMER_02))
            self.assertTrue(verify_password(password, user.password_hash))


if __name__ == "__main__":
    unittest.main()
