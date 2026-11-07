"""FastAPI tests using temporary SQLite databases and saved inference artifacts."""

from pathlib import Path
import secrets
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.auth import create_access_token, hash_password
from api.main import create_app
from database.config import create_database_engine
from database.models import Offer, RetentionIntervention
from services.churn_inference import ChurnInferenceService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sample_features() -> dict[str, object]:
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


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inference_service = ChurnInferenceService(
            preprocessor_path=PROJECT_ROOT / "models" / "preprocessor.pkl",
            model_path=PROJECT_ROOT / "models" / "churn_model.pkl",
        )

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "api-test.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.auth_secret = secrets.token_urlsafe(48)
        self.admin_password = "admin-api-tests-password-2026!"
        self.admin_password_hash = hash_password(self.admin_password)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_directory.cleanup()

    def client(self, *, inference_factory=None) -> TestClient:
        app = create_app(
            database_engine=self.engine,
            inference_service=(None if inference_factory else self.inference_service),
            inference_service_factory=inference_factory,
            auth_secret_key=self.auth_secret,
            admin_email="admin@example.test",
            admin_password_hash=self.admin_password_hash,
        )
        return TestClient(app)

    def admin_headers(self) -> dict[str, str]:
        token = create_access_token(0, self.auth_secret)
        return {"Authorization": f"Bearer {token}"}

    def test_health_is_public_and_returns_simple_status(self) -> None:
        with self.client() as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})

    def test_internal_offer_catalog_requires_admin_authentication(self) -> None:
        with self.client() as client:
            response = client.get("/offers")
        self.assertEqual(response.status_code, 401)

    def test_retention_preview_requires_admin_authentication(self) -> None:
        with self.client() as client:
            response = client.post(
                "/retention/decide",
                json={"customers": [], "total_budget": 0},
            )
        self.assertEqual(response.status_code, 401)

    def test_predict_returns_probability_model_version_and_separate_customer_id(self) -> None:
        with self.client() as client:
            response = client.post(
                "/predict",
                json={"customer_id": "customer-5", "features": sample_features()},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["customer_id"], "customer-5")
        self.assertGreaterEqual(body["churn_probability"], 0)
        self.assertLessEqual(body["churn_probability"], 1)
        self.assertTrue(body["model_version"].startswith("sha256-"))

    def test_predict_rejects_missing_and_unexpected_model_features(self) -> None:
        features = sample_features()
        del features["Tenure"]
        with self.client() as client:
            missing_response = client.post(
                "/predict", json={"customer_id": 1, "features": features}
            )
            extra = sample_features()
            extra["Churn"] = 0
            extra_response = client.post(
                "/predict", json={"customer_id": 1, "features": extra}
            )

        self.assertEqual(missing_response.status_code, 422)
        self.assertIn("missing features", missing_response.json()["detail"])
        self.assertEqual(extra_response.status_code, 422)
        self.assertIn("unexpected features", extra_response.json()["detail"])

    def test_predict_rejects_unexpected_top_level_request_fields(self) -> None:
        with self.client() as client:
            response = client.post(
                "/predict",
                json={
                    "customer_id": 1,
                    "features": sample_features(),
                    "artifact_path": "models/other.pkl",
                },
            )
        self.assertEqual(response.status_code, 422)

    def test_retention_endpoint_calls_engine_and_does_not_persist_decisions(self) -> None:
        request = {
            "customers": [
                {
                    "customer_id": "small",
                    "churn_probability": 0.5,
                    "historical_revenue": 1000,
                },
                {
                    "customer_id": "large",
                    "churn_probability": 0.9,
                    "historical_revenue": 2000,
                },
            ],
            "total_budget": 100,
        }
        with self.client() as client:
            response = client.post(
                "/retention/decide", json=request, headers=self.admin_headers()
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [customer["selected_intervention"] for customer in body["customers"]],
            ["SMALL_DISCOUNT", "NO_OFFER"],
        )
        self.assertEqual(body["summary"]["total_estimated_budget_allocated"], 100)
        with Session(self.engine) as session:
            self.assertEqual(session.query(Offer).count(), 4)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)

    def test_retention_endpoint_rejects_invalid_budget_and_probability(self) -> None:
        invalid_budget = {
            "customers": [],
            "total_budget": -1,
        }
        invalid_probability = {
            "customers": [
                {
                    "customer_id": "bad-risk",
                    "churn_probability": 1.2,
                    "historical_revenue": 100,
                }
            ],
            "total_budget": 100,
        }
        with self.client() as client:
            budget_response = client.post(
                "/retention/decide", json=invalid_budget,
                headers=self.admin_headers(),
            )
            probability_response = client.post(
                "/retention/decide", json=invalid_probability,
                headers=self.admin_headers(),
            )

        self.assertEqual(budget_response.status_code, 422)
        self.assertEqual(probability_response.status_code, 422)

    def test_predict_reports_unavailable_artifacts_without_exposing_paths(self) -> None:
        def unavailable_service():
            raise FileNotFoundError("private local model path")

        with self.client(inference_factory=unavailable_service) as client:
            health = client.get("/health")
            prediction = client.post(
                "/predict",
                json={"customer_id": 7, "features": sample_features()},
            )

        self.assertEqual(health.status_code, 200)
        self.assertEqual(prediction.status_code, 503)
        self.assertNotIn("private local model path", prediction.text)


if __name__ == "__main__":
    unittest.main()
