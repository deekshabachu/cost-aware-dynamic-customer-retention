"""HTTP tests for the persisted customer retention refresh endpoint."""

from decimal import Decimal
import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.auth import create_access_token, hash_password
from api.main import create_app
from database.config import create_database_engine
from database.models import (
    CustomerActivity,
    Order,
    RetentionIntervention,
    RetentionPrediction,
    User,
    Offer,
)
from services.churn_inference import ChurnPrediction
from services.customer_retention import MODEL_FEATURES_EVENT_TYPE


def raw_features() -> dict[str, object]:
    return {
        "Tenure": 10,
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
    def predict_batch(self, customer_ids, features):
        expected = set(raw_features())
        for row in features:
            missing = expected - set(row)
            unexpected = set(row) - expected
            if missing or unexpected:
                problems = []
                if missing:
                    problems.append(f"missing features: {sorted(missing)}")
                if unexpected:
                    problems.append(f"unexpected features: {sorted(unexpected)}")
                raise ValueError("Invalid input schema (" + "; ".join(problems) + ").")
        return [
            ChurnPrediction(customer_id, 0.5, "api-test-model")
            for customer_id in customer_ids
        ]


class CustomerRetentionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "retention-api-test.db"
        self.engine = create_database_engine(f"sqlite:///{path.as_posix()}")
        self.secret = secrets.token_urlsafe(48)
        self.admin_email = "retention-admin@example.test"
        self.admin_password = "admin-refresh-tests-password-2026!"
        app = create_app(
            database_engine=self.engine,
            inference_service=FakeInferenceService(),
            auth_secret_key=self.secret,
            admin_email=self.admin_email,
            admin_password_hash=hash_password(self.admin_password),
        )
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.engine.dispose()
        self.temp_directory.cleanup()

    def add_customer(
        self, *, include_snapshot: bool = True, email: str = "api-customer@example.test"
    ) -> int:
        with Session(self.engine) as session:
            user = User(
                name="API Customer",
                email=email,
                password_hash="test-hash-value",
                role="customer",
            )
            session.add(user)
            session.flush()
            session.add(
                Order(
                    user_id=user.id,
                    total_amount=Decimal("500.00"),
                    status="completed",
                )
            )
            if include_snapshot:
                session.add(
                    CustomerActivity(
                        user_id=user.id,
                        event_type=MODEL_FEATURES_EVENT_TYPE,
                        event_metadata=raw_features(),
                    )
                )
            session.commit()
            return user.id

    def headers_for(self, customer_id: int) -> dict[str, str]:
        token = create_access_token(customer_id, self.secret)
        return {"Authorization": f"Bearer {token}"}

    def admin_headers(self) -> dict[str, str]:
        response = self.client.post(
            "/admin/auth/login",
            json={"email": self.admin_email, "password": self.admin_password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_refresh_endpoint_returns_and_persists_end_to_end_result(self) -> None:
        customer_id = self.add_customer()
        response = self.client.post(
            "/retention/refresh",
            headers=self.admin_headers(),
            json={"customer_ids": [customer_id], "total_budget": 100},
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["predictions"][0]["model_version"], "api-test-model")
        self.assertEqual(body["decisions"][0]["historical_revenue"], 500)
        self.assertEqual(body["decisions"][0]["selected_intervention"], "SMALL_DISCOUNT")
        with Session(self.engine) as session:
            prediction = session.scalars(select(RetentionPrediction)).one()
            intervention = session.scalars(select(RetentionIntervention)).one()
            self.assertEqual(prediction.customer_value, Decimal("500.00"))
            self.assertEqual(intervention.status, "active")

    def test_customer_cannot_probe_or_refresh_an_unknown_customer_id(self) -> None:
        requester_id = self.add_customer()
        response = self.client.post(
            "/retention/refresh",
            headers=self.headers_for(requester_id),
            json={"customer_ids": [999], "total_budget": 100},
        )
        self.assertEqual(response.status_code, 401)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)

    def test_customer_cannot_refresh_another_customers_record(self) -> None:
        requester_id = self.add_customer(email="requester@example.test")
        other_id = self.add_customer(email="other-customer@example.test")

        response = self.client.post(
            "/retention/refresh",
            headers=self.headers_for(requester_id),
            json={"customer_ids": [other_id], "total_budget": 100},
        )

        self.assertEqual(response.status_code, 401)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)

    def test_customer_cannot_mix_own_and_another_customers_ids(self) -> None:
        requester_id = self.add_customer(email="requester@example.test")
        other_id = self.add_customer(email="other-customer@example.test")

        response = self.client.post(
            "/retention/refresh",
            headers=self.headers_for(requester_id),
            json={"customer_ids": [requester_id, other_id], "total_budget": 100},
        )

        self.assertEqual(response.status_code, 401)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)

    def test_refresh_endpoint_returns_422_without_stored_feature_snapshot(self) -> None:
        customer_id = self.add_customer(include_snapshot=False)
        response = self.client.post(
            "/retention/refresh",
            headers=self.admin_headers(),
            json={"customer_ids": [customer_id], "total_budget": 100},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("no model feature snapshot", response.json()["detail"])

    def test_refresh_endpoint_returns_422_for_incomplete_stored_features(self) -> None:
        customer_id = self.add_customer()
        with Session(self.engine) as session:
            snapshot = session.query(CustomerActivity).filter_by(user_id=customer_id).one()
            snapshot.event_metadata = {"Tenure": 10}
            session.commit()

        response = self.client.post(
            "/retention/refresh",
            headers=self.admin_headers(),
            json={"customer_ids": [customer_id], "total_budget": 100},
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("missing features", response.json()["detail"])

    def test_refresh_endpoint_requires_an_explicit_nonnegative_budget(self) -> None:
        customer_id = self.add_customer()
        response = self.client.post(
            "/retention/refresh",
            headers=self.admin_headers(),
            json={"customer_ids": [1], "total_budget": -1},
        )
        self.assertEqual(response.status_code, 422)

    def test_refresh_endpoint_rejects_unauthenticated_requests(self) -> None:
        customer_id = self.add_customer()
        response = self.client.post(
            "/retention/refresh",
            json={"customer_ids": [customer_id], "total_budget": 100},
        )
        self.assertEqual(response.status_code, 401)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)

    def test_customer_offer_returns_only_the_authenticated_users_active_offer(self) -> None:
        customer_id = self.add_customer(email="assigned@example.test")
        other_id = self.add_customer(email="other@example.test")
        with Session(self.engine) as session:
            offer = session.scalar(select(Offer).where(Offer.code == "SMALL_DISCOUNT"))
            session.add(
                RetentionIntervention(
                    user_id=customer_id,
                    offer_id=offer.id,
                    intervention_cost=Decimal("100.00"),
                    priority_score=Decimal("250.0000"),
                    decision_reason="Eligible customer prioritized by score.",
                    status="active",
                )
            )
            session.commit()

        own = self.client.get("/retention/offer", headers=self.headers_for(customer_id))
        other = self.client.get("/retention/offer", headers=self.headers_for(other_id))

        self.assertEqual(own.status_code, 200, own.text)
        self.assertTrue(own.json()["assigned"])
        customer_offer = own.json()["intervention"]
        self.assertEqual(customer_offer["offer"]["name"], "Your LittleLeaf discount")
        self.assertIn("description", customer_offer["offer"])
        self.assertNotIn("code", customer_offer["offer"])
        self.assertNotIn("maximum_cost", customer_offer["offer"])
        self.assertNotIn("intervention_cost", customer_offer)
        self.assertNotIn("priority_score", customer_offer)
        self.assertNotIn("decision_reason", customer_offer)
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual(other.json(), {"assigned": False, "intervention": None})

    def test_customer_offer_requires_authentication_and_reports_no_assignment(self) -> None:
        customer_id = self.add_customer()
        denied = self.client.get("/retention/offer")
        allowed = self.client.get("/retention/offer", headers=self.headers_for(customer_id))
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json(), {"assigned": False, "intervention": None})

    def test_customer_offer_does_not_show_an_inactive_offer_as_assigned(self) -> None:
        customer_id = self.add_customer(email="inactive-offer@example.test")
        with Session(self.engine) as session:
            offer = session.scalar(select(Offer).where(Offer.code == "SMALL_DISCOUNT"))
            offer.active = False
            session.add(
                RetentionIntervention(
                    user_id=customer_id,
                    offer_id=offer.id,
                    intervention_cost=Decimal("100.00"),
                    priority_score=Decimal("250.0000"),
                    decision_reason="Test inactive offer filtering.",
                    status="active",
                )
            )
            session.commit()

        response = self.client.get(
            "/retention/offer", headers=self.headers_for(customer_id)
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"assigned": False, "intervention": None})

    def test_customer_offer_reports_database_failure_safely(self) -> None:
        customer_id = self.add_customer()
        with Session(self.engine) as session:
            session.execute(text("DROP TABLE retention_interventions"))
            session.commit()

        with self.assertLogs("api.main", level="ERROR"):
            response = self.client.get(
                "/retention/offer", headers=self.headers_for(customer_id)
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "The assigned offer could not be loaded.")


if __name__ == "__main__":
    unittest.main()
