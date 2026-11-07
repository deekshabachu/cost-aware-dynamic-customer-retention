"""Tests for the opt-in, repeatable demo-data seed script."""

from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import (
    CustomerActivity,
    Order,
    RetentionIntervention,
    RetentionPrediction,
    User,
)
from scripts.seed_demo_data import (
    DEMO_CUSTOMERS,
    DEMO_EMAIL_DOMAIN,
    DEMO_MANIFEST_EVENT_TYPE,
    DEMO_NAMESPACE,
    PREPROCESSOR_PATH,
    seed_demo_data,
)
from services.customer_retention import MODEL_FEATURES_EVENT_TYPE


class DemoSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "seed-test.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        initialize_database(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_directory.cleanup()

    def test_seed_is_repeatable_and_preserves_unrelated_data(self) -> None:
        with Session(self.engine) as session:
            unrelated = User(
                name="Unrelated Account",
                email="unrelated@example.test",
                password_hash="existing-hash",
                role="customer",
            )
            session.add(unrelated)
            session.flush()
            unrelated_id = unrelated.id
            session.add(
                Order(
                    user_id=unrelated.id,
                    total_amount=Decimal("88.50"),
                    status="completed",
                )
            )
            session.add(
                CustomerActivity(
                    user_id=unrelated.id,
                    event_type="existing_event",
                    event_metadata={"keep": True},
                )
            )
            session.commit()

        first_run = seed_demo_data(self.engine)
        counts_after_first = self._counts()
        second_run = seed_demo_data(self.engine)
        counts_after_second = self._counts()

        self.assertEqual(first_run, second_run)
        self.assertEqual(len(first_run), 9)
        self.assertEqual(counts_after_first, counts_after_second)
        with Session(self.engine) as session:
            saved_unrelated = session.get(User, unrelated_id)
            self.assertEqual(saved_unrelated.name, "Unrelated Account")
            self.assertEqual(saved_unrelated.email, "unrelated@example.test")
            self.assertEqual(
                session.scalar(
                    select(func.sum(Order.total_amount)).where(
                        Order.user_id == unrelated_id,
                        Order.status == "completed",
                    )
                ),
                Decimal("88.50"),
            )
            unrelated_activity = session.scalars(
                select(CustomerActivity).where(
                    CustomerActivity.user_id == unrelated_id
                )
            ).one()
            self.assertEqual(unrelated_activity.event_metadata, {"keep": True})

    def test_snapshots_match_saved_preprocessor_and_transform_successfully(self) -> None:
        seed_demo_data(self.engine)
        preprocessor = joblib.load(PREPROCESSOR_PATH)
        raw_names = list(preprocessor.feature_names_in_)
        categorical_names = list(preprocessor.transformers_[1][2])
        encoder = preprocessor.named_transformers_["categorical"].named_steps["encoder"]
        valid_categories = {
            name: set(values)
            for name, values in zip(categorical_names, encoder.categories_)
        }

        with Session(self.engine) as session:
            snapshots = session.scalars(
                select(CustomerActivity)
                .where(CustomerActivity.event_type == MODEL_FEATURES_EVENT_TYPE)
                .order_by(CustomerActivity.user_id)
            ).all()

        self.assertEqual(len(snapshots), len(DEMO_CUSTOMERS))
        feature_rows = []
        for snapshot in snapshots:
            features = snapshot.event_metadata
            self.assertEqual(set(features), set(raw_names))
            for name, categories in valid_categories.items():
                self.assertIn(features[name], categories)
            feature_rows.append(features)

        transformed = preprocessor.transform(
            pd.DataFrame(feature_rows, columns=raw_names)
        )
        self.assertEqual(transformed.shape[0], len(DEMO_CUSTOMERS))
        self.assertEqual(transformed.shape[1], len(preprocessor.get_feature_names_out()))

    def test_completed_order_revenue_varies_and_some_customers_have_none(self) -> None:
        seed_demo_data(self.engine)
        with Session(self.engine) as session:
            customers = session.scalars(
                select(User).where(User.email.endswith(f"@{DEMO_EMAIL_DOMAIN}"))
            ).all()
            revenues = {
                user.email: session.scalar(
                    select(func.sum(Order.total_amount)).where(
                        Order.user_id == user.id,
                        Order.status == "completed",
                    )
                )
                or Decimal("0.00")
                for user in customers
            }

        self.assertEqual(len(revenues), 9)
        self.assertGreater(len(set(revenues.values())), 5)
        self.assertGreaterEqual(
            sum(value == Decimal("0.00") for value in revenues.values()), 2
        )
        self.assertIn(Decimal("1798.00"), revenues.values())
        self.assertIn(Decimal("3950.00"), revenues.values())

    def test_passwords_are_scrypt_hashes_and_no_refresh_is_triggered(self) -> None:
        seed_demo_data(self.engine)
        with Session(self.engine) as session:
            demo_users = session.scalars(
                select(User).where(User.email.endswith(f"@{DEMO_EMAIL_DOMAIN}"))
            ).all()
            password_hashes = [user.password_hash for user in demo_users]
            self.assertTrue(all(value.startswith("scrypt$16384$8$1$") for value in password_hashes))
            self.assertEqual(len(set(password_hashes)), len(password_hashes))
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)
            manifests = session.scalars(
                select(CustomerActivity).where(
                    CustomerActivity.event_type == DEMO_MANIFEST_EVENT_TYPE
                )
            ).all()
            self.assertEqual(len(manifests), 9)
            self.assertTrue(
                all(row.event_metadata["namespace"] == DEMO_NAMESPACE for row in manifests)
            )

    def test_reserved_email_collision_without_manifest_is_not_overwritten(self) -> None:
        email = f"customer01@{DEMO_EMAIL_DOMAIN}"
        with Session(self.engine) as session:
            session.add(
                User(
                    name="Existing Unrelated User",
                    email=email,
                    password_hash="keep-this-hash",
                    role="customer",
                )
            )
            session.commit()

        with self.assertRaisesRegex(RuntimeError, "already exists without this script's seed marker"):
            seed_demo_data(self.engine)
        with Session(self.engine) as session:
            self.assertEqual(session.query(User).count(), 1)
            saved = session.scalars(select(User)).one()
            self.assertEqual(saved.name, "Existing Unrelated User")
            self.assertEqual(saved.password_hash, "keep-this-hash")

    def _counts(self) -> tuple[int, int, int, int, int]:
        with Session(self.engine) as session:
            return (
                session.query(User).count(),
                session.query(Order).count(),
                session.query(CustomerActivity)
                .filter_by(event_type=MODEL_FEATURES_EVENT_TYPE)
                .count(),
                session.query(CustomerActivity)
                .filter_by(event_type=DEMO_MANIFEST_EVENT_TYPE)
                .count(),
                session.query(RetentionPrediction).count(),
            )


if __name__ == "__main__":
    unittest.main()
