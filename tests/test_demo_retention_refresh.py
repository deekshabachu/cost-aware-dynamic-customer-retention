"""Tests for the explicit local multi-customer retention refresh helper."""

from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import RetentionIntervention, RetentionPrediction, User
from scripts.refresh_demo_retention import refresh_demo_customers
from scripts.seed_demo_data import seed_demo_data
from services.churn_inference import ChurnPrediction


class SelectedCustomerInference:
    """Fixed outputs isolate the refresh workflow from model behavior in this test."""

    def predict_batch(self, customer_ids, customers):
        self.assert_selected = list(customer_ids)
        probabilities = {1: 0.10, 2: 0.80}
        return [
            ChurnPrediction(customer_id, probabilities[customer_id], "cli-test-model")
            for customer_id in customer_ids
        ]


class DemoRetentionRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "demo-refresh-test.db"
        self.engine = create_database_engine(f"sqlite:///{path.as_posix()}")
        initialize_database(self.engine)
        seed_demo_data(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_directory.cleanup()

    def test_local_workflow_refreshes_only_explicit_customers(self) -> None:
        inference = SelectedCustomerInference()
        with Session(self.engine) as session:
            result = refresh_demo_customers(
                session=session,
                inference_service=inference,
                customer_ids=[1, 2],
                total_budget=60,
            )

        self.assertEqual(inference.assert_selected, [1, 2])
        self.assertEqual(len(result.predictions), 2)
        decisions = {item.customer_id: item for item in result.decisions.customers}
        self.assertEqual(decisions[1].selected_intervention, "NO_OFFER")
        self.assertEqual(decisions[2].selected_intervention, "FREE_SHIPPING")
        self.assertEqual(result.decisions.summary.remaining_budget, 0)

        with Session(self.engine) as session:
            predictions = session.scalars(select(RetentionPrediction)).all()
            interventions = session.scalars(select(RetentionIntervention)).all()
            self.assertEqual({row.user_id for row in predictions}, {1, 2})
            self.assertEqual({row.user_id for row in interventions}, {1, 2})
            self.assertEqual(len(predictions), 2)
            self.assertEqual(len(interventions), 2)
            customer_2 = next(row for row in interventions if row.user_id == 2)
            self.assertEqual(customer_2.status, "active")
            self.assertEqual(customer_2.intervention_cost, Decimal("60.00"))
            self.assertEqual(
                session.scalars(
                    select(RetentionPrediction).where(RetentionPrediction.user_id == 3)
                ).all(),
                [],
            )

    def test_local_workflow_rejects_unrelated_customer_ids(self) -> None:
        with Session(self.engine) as session:
            unrelated = User(
                name="Unrelated Customer",
                email="unrelated@example.test",
                password_hash="test-only-hash",
                role="customer",
            )
            session.add(unrelated)
            session.commit()
            unrelated_id = unrelated.id
            inference = SelectedCustomerInference()

            with self.assertRaisesRegex(ValueError, "seed-marked demo customers"):
                refresh_demo_customers(session, inference, [unrelated_id], 60)

        with Session(self.engine) as session:
            self.assertEqual(session.scalars(select(RetentionPrediction)).all(), [])
            self.assertEqual(session.scalars(select(RetentionIntervention)).all(), [])


if __name__ == "__main__":
    unittest.main()
