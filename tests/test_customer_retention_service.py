"""Persistence and calculation tests for database-backed retention refreshes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import (
    CustomerActivity,
    Order,
    RetentionIntervention,
    RetentionOfferValidity,
    RetentionPrediction,
    User,
)
from services.churn_inference import ChurnPrediction
from services.customer_retention import (
    MODEL_FEATURES_EVENT_TYPE,
    MissingCustomerFeaturesError,
    UnknownCustomerError,
    refresh_customer_retention,
)


def feature_snapshot(tenure: int = 10) -> dict[str, object]:
    return {
        "Tenure": tenure,
        "PreferredLoginDevice": "Mobile Phone",
        "CityTier": 1,
        "WarehouseToHome": 6,
        "PreferredPaymentMode": "Debit Card",
        "Gender": "Female",
        "HourSpendOnApp": 3,
        "NumberOfDeviceRegistered": 4,
        "PreferedOrderCat": "Laptop & Accessory",
        "SatisfactionScore": 3,
        "MaritalStatus": "Single",
        "NumberOfAddress": 2,
        "Complain": 0,
        "OrderAmountHikeFromlastYear": 15,
        "CouponUsed": 1,
        "OrderCount": 2,
        "DaySinceLastOrder": 5,
        "CashbackAmount": 150.0,
    }


class FakeInferenceService:
    def __init__(self, probabilities: list[float] | None = None) -> None:
        self.probabilities = probabilities or [0.5]
        self.calls: list[tuple[list[int], list[dict[str, object]]]] = []

    def predict_batch(self, customer_ids, customers):
        ids = list(customer_ids)
        records = list(customers)
        self.calls.append((ids, records))
        if len(ids) != len(records):
            raise ValueError("Customer IDs and feature rows must have matching lengths.")
        if any("Tenure" not in record for record in records):
            raise ValueError("Invalid input schema (missing features: ['Tenure']).")
        call_number = len(self.calls) - 1
        probability = self.probabilities[min(call_number, len(self.probabilities) - 1)]
        return [
            ChurnPrediction(customer_id, probability, f"test-model-{call_number + 1}")
            for customer_id in ids
        ]


class CustomerRetentionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite:///:memory:")
        initialize_database(self.engine)
        with Session(self.engine) as session:
            self.user = User(
                name="Test Customer",
                email="retention@example.test",
                password_hash="test-hash-value",
                role="customer",
            )
            session.add(self.user)
            session.flush()
            self.customer_id = self.user.id
            session.add_all(
                [
                    Order(
                        user_id=self.user.id,
                        total_amount=Decimal("1200.00"),
                        status="completed",
                    ),
                    Order(
                        user_id=self.user.id,
                        total_amount=Decimal("900.00"),
                        status="completed",
                    ),
                    Order(
                        user_id=self.user.id,
                        total_amount=Decimal("500.00"),
                        status="pending",
                    ),
                    Order(
                        user_id=self.user.id,
                        total_amount=Decimal("700.00"),
                        status="cancelled",
                    ),
                ]
            )
            session.add(
                CustomerActivity(
                    user_id=self.user.id,
                    event_type=MODEL_FEATURES_EVENT_TYPE,
                    event_metadata=feature_snapshot(),
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            )
            session.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_completed_order_revenue_inference_and_decision_are_persisted(self) -> None:
        inference = FakeInferenceService([0.5])
        with Session(self.engine) as session:
            result = refresh_customer_retention(
                session, inference, [self.customer_id], total_budget=100
            )

        self.assertEqual(result.predictions[0].churn_probability, 0.5)
        decision = result.decisions.customers[0]
        self.assertEqual(decision.historical_revenue, 2100)
        self.assertEqual(decision.selected_intervention, "SMALL_DISCOUNT")
        self.assertEqual(inference.calls[0][0], [self.customer_id])
        self.assertEqual(inference.calls[0][1][0]["Tenure"], 10)

        with Session(self.engine) as session:
            prediction = session.scalars(select(RetentionPrediction)).one()
            intervention = session.scalars(select(RetentionIntervention)).one()
            self.assertEqual(prediction.churn_probability, Decimal("0.5000"))
            self.assertEqual(prediction.customer_value, Decimal("2100.00"))
            self.assertEqual(prediction.model_version, "test-model-1")
            self.assertEqual(intervention.offer.code, "SMALL_DISCOUNT")
            self.assertEqual(intervention.intervention_cost, Decimal("100.00"))
            self.assertEqual(intervention.status, "active")
            validity = session.scalars(select(RetentionOfferValidity)).one()
            self.assertEqual(
                validity.expires_at - intervention.created_at,
                timedelta(days=7),
            )

    def test_refresh_uses_latest_feature_snapshot_and_supersedes_prior_offer(self) -> None:
        with Session(self.engine) as session:
            session.add(
                CustomerActivity(
                    user_id=self.customer_id,
                    event_type=MODEL_FEATURES_EVENT_TYPE,
                    event_metadata=feature_snapshot(tenure=2),
                    created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                )
            )
            session.commit()

        inference = FakeInferenceService([0.5, 0.9])
        with Session(self.engine) as session:
            refresh_customer_retention(session, inference, [self.customer_id], 250)
        with Session(self.engine) as session:
            result = refresh_customer_retention(session, inference, [self.customer_id], 250)

        self.assertEqual(inference.calls[0][1][0]["Tenure"], 2)
        self.assertEqual(result.decisions.customers[0].selected_intervention, "LARGE_DISCOUNT")
        with Session(self.engine) as session:
            predictions = session.scalars(
                select(RetentionPrediction).order_by(RetentionPrediction.id)
            ).all()
            interventions = session.scalars(
                select(RetentionIntervention).order_by(RetentionIntervention.id)
            ).all()
            self.assertEqual(len(predictions), 2)
            self.assertEqual(len(interventions), 2)
            self.assertEqual(
                [row.status for row in interventions], ["superseded", "active"]
            )
            self.assertEqual(
                sum(row.status == "active" for row in interventions), 1
            )

    def test_no_offer_refresh_supersedes_old_active_offer(self) -> None:
        inference = FakeInferenceService([0.5, 0.1])
        with Session(self.engine) as session:
            refresh_customer_retention(session, inference, [self.customer_id], 100)
        with Session(self.engine) as session:
            result = refresh_customer_retention(session, inference, [self.customer_id], 100)

        self.assertEqual(result.decisions.customers[0].selected_intervention, "NO_OFFER")
        with Session(self.engine) as session:
            statuses = session.scalars(
                select(RetentionIntervention.status).order_by(RetentionIntervention.id)
            ).all()
        self.assertEqual(statuses, ["superseded", "no_offer"])

    def test_unknown_customer_is_rejected_before_inference(self) -> None:
        inference = FakeInferenceService()
        with Session(self.engine) as session:
            with self.assertRaisesRegex(UnknownCustomerError, "Customer 999 was not found"):
                refresh_customer_retention(session, inference, [999], 100)
        self.assertEqual(inference.calls, [])

    def test_missing_feature_snapshot_is_rejected_before_inference(self) -> None:
        inference = FakeInferenceService()
        with Session(self.engine) as session:
            user = session.get(User, self.customer_id)
            session.query(CustomerActivity).filter_by(user_id=user.id).delete()
            session.commit()
        with Session(self.engine) as session:
            with self.assertRaisesRegex(MissingCustomerFeaturesError, "no model feature snapshot"):
                refresh_customer_retention(session, inference, [self.customer_id], 100)
        self.assertEqual(inference.calls, [])

    def test_invalid_snapshot_features_are_rejected_and_not_persisted(self) -> None:
        inference = FakeInferenceService()
        with Session(self.engine) as session:
            snapshot = session.scalars(select(CustomerActivity)).one()
            snapshot.event_metadata = {"Churn": 0}
            session.commit()
        with Session(self.engine) as session:
            with self.assertRaisesRegex(ValueError, "missing features"):
                refresh_customer_retention(session, inference, [self.customer_id], 100)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)


if __name__ == "__main__":
    unittest.main()
