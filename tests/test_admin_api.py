"""Security and persistence tests for protected administrator workflows."""

from decimal import Decimal
from datetime import timedelta
import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import create_access_token, hash_password
from api.main import create_app
from database.config import create_database_engine
from database.models import (
    CustomerActivity,
    Offer,
    Order,
    Product,
    RetentionBudgetSetting,
    RetentionIntervention,
    RetentionOfferRedemption,
    RetentionOfferValidity,
    RetentionPrediction,
    User,
)
from database.base import utc_now
from services.churn_inference import ChurnPrediction
from services.customer_retention import MODEL_FEATURES_EVENT_TYPE


ADMIN_EMAIL = "retention-admin@example.test"
ADMIN_PASSWORD = "Admin-password-for-tests-2026!"


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
    probabilities = {1: 0.8, 2: 0.5, 3: 0.2}
    feature_names = tuple(raw_features().keys())

    def predict_batch(self, customer_ids, features):
        return [
            ChurnPrediction(customer_id, self.probabilities.get(customer_id, 0.4), "admin-test-model")
            for customer_id in customer_ids
        ]


class FailingInferenceService:
    feature_names = tuple(raw_features().keys())

    def predict_batch(self, customer_ids, features):
        raise RuntimeError("test inference failure")


class AdminApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "admin-test.db"
        self.engine = create_database_engine(f"sqlite:///{path.as_posix()}")
        self.secret = secrets.token_urlsafe(48)
        self.password_hash = hash_password(ADMIN_PASSWORD)
        self.client_context = self._open_client()
        self.client = self.client_context.__enter__()

    def _open_client(self):
        app = create_app(
            database_engine=self.engine,
            inference_service=FakeInferenceService(),
            auth_secret_key=self.secret,
            admin_email=ADMIN_EMAIL,
            admin_password_hash=self.password_hash,
        )
        return TestClient(app)

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.engine.dispose()
        self.temp_directory.cleanup()

    def admin_headers(self) -> dict[str, str]:
        response = self.client.post(
            "/admin/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def add_customer(
        self, email: str, *, revenue: str, snapshot: bool = True
    ) -> int:
        with Session(self.engine) as session:
            user = User(
                name="Test customer",
                email=email,
                password_hash="scrypt-test-placeholder",
                role="customer",
            )
            session.add(user)
            session.flush()
            if revenue != "0":
                session.add(
                    Order(
                        user_id=user.id,
                        total_amount=Decimal(revenue),
                        status="completed",
                    )
                )
            if snapshot:
                session.add(
                    CustomerActivity(
                        user_id=user.id,
                        event_type=MODEL_FEATURES_EVENT_TYPE,
                        event_metadata=raw_features(),
                    )
                )
            session.commit()
            return user.id

    def test_admin_login_and_authorization_are_separate_from_customers(self) -> None:
        customer_id = self.add_customer("ordinary@example.test", revenue="25.00")
        customer_password = "ordinary-customer-password-2026!"
        with Session(self.engine) as session:
            customer = session.get(User, customer_id)
            customer.password_hash = hash_password(customer_password)
            session.commit()

        customer_login = self.client.post(
            "/auth/login",
            json={"email": "ordinary@example.test", "password": customer_password},
        )
        self.assertEqual(customer_login.status_code, 200)
        actual_customer_headers = {
            "Authorization": f"Bearer {customer_login.json()['access_token']}"
        }
        self.assertEqual(
            self.client.get("/admin/dashboard", headers=actual_customer_headers).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/admin/auth/login",
                json={"email": "ordinary@example.test", "password": customer_password},
            ).status_code,
            401,
        )
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 401)
        bad_password = self.client.post(
            "/admin/auth/login",
            json={"email": ADMIN_EMAIL, "password": "incorrect-admin-password"},
        )
        self.assertEqual(bad_password.status_code, 401)
        four_character_bad_password = self.client.post(
            "/admin/auth/login",
            json={"email": ADMIN_EMAIL, "password": "Nope"},
        )
        self.assertEqual(four_character_bad_password.status_code, 401)
        bad_email = self.client.post(
            "/admin/auth/login",
            json={"email": "ordinary@example.test", "password": ADMIN_PASSWORD},
        )
        self.assertEqual(bad_email.status_code, 401)

        customer_token = create_access_token(customer_id, self.secret)
        customer_headers = {"Authorization": f"Bearer {customer_token}"}
        self.assertEqual(self.client.get("/admin/dashboard", headers=customer_headers).status_code, 401)
        self.assertEqual(self.client.get("/offers", headers=customer_headers).status_code, 401)
        self.assertEqual(
            self.client.put(
                "/admin/budget",
                headers=customer_headers,
                json={"total_budget": 100},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/admin/retention/allocate", headers=customer_headers).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/admin/customers/1/evaluate",
                headers=customer_headers,
                json={"eligibility_threshold": 0.3},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/admin/retention/evaluate-all",
                headers=customer_headers,
                json={"eligibility_threshold": 0.1},
            ).status_code,
            401,
        )

        admin_headers = self.admin_headers()
        self.assertEqual(self.client.get("/admin/dashboard", headers=admin_headers).status_code, 200)
        self.assertEqual(self.client.get("/offers", headers=admin_headers).status_code, 200)
        # Admin tokens are not valid customer sessions.
        self.assertEqual(self.client.get("/auth/me", headers=admin_headers).status_code, 401)

    def test_missing_admin_credentials_fail_closed(self) -> None:
        app = create_app(
            database_engine=self.engine,
            inference_service=FakeInferenceService(),
            auth_secret_key=self.secret,
            admin_email="",
            admin_password_hash="",
        )
        with TestClient(app) as client:
            response = client.post(
                "/admin/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            )
        self.assertEqual(response.status_code, 503)

    def test_budget_is_saved_without_mutating_assignments_and_survives_app_recreation(self) -> None:
        customer_id = self.add_customer("budget@example.test", revenue="300.00")
        headers = self.admin_headers()
        first = self.client.get("/admin/dashboard", headers=headers).json()
        self.assertFalse(first["budget_configured"])

        saved = self.client.put(
            "/admin/budget", headers=headers, json={"total_budget": 225.50}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["current_budget"], 225.5)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)
            setting = session.get(RetentionBudgetSetting, 1)
            self.assertEqual(setting.total_budget, Decimal("225.50"))

        self.client_context.__exit__(None, None, None)
        self.client_context = self._open_client()
        self.client = self.client_context.__enter__()
        persisted = self.client.get("/admin/dashboard", headers=headers)
        self.assertEqual(persisted.status_code, 200, persisted.text)
        self.assertEqual(persisted.json()["current_budget"], 225.5)
        self.assertEqual(persisted.json()["total_customers"], 1)
        self.assertEqual(customer_id, 1)

    def test_invalid_budget_is_rejected_without_creating_setting(self) -> None:
        response = self.client.put(
            "/admin/budget",
            headers=self.admin_headers(),
            json={"total_budget": -1},
        )
        self.assertEqual(response.status_code, 422)
        with Session(self.engine) as session:
            self.assertIsNone(session.get(RetentionBudgetSetting, 1))

    def test_allocation_uses_saved_budget_engine_and_persists_atomic_summary(self) -> None:
        high_value = self.add_customer("high@example.test", revenue="3000.00")
        medium_value = self.add_customer("medium@example.test", revenue="1000.00")
        low_risk = self.add_customer("low@example.test", revenue="0")
        no_snapshot = self.add_customer("missing@example.test", revenue="500.00", snapshot=False)
        headers = self.admin_headers()

        missing_budget = self.client.post("/admin/retention/allocate", headers=headers)
        self.assertEqual(missing_budget.status_code, 409)
        self.assertEqual(
            self.client.put("/admin/budget", headers=headers, json={"total_budget": 100}).status_code,
            200,
        )
        result = self.client.post("/admin/retention/allocate", headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        allocation = body["latest_allocation"]
        self.assertEqual(allocation["initial_budget"], 100)
        self.assertEqual(allocation["total_estimated_budget_allocated"], 100)
        self.assertEqual(allocation["remaining_budget"], 0)
        self.assertEqual(allocation["customer_count"], 3)
        self.assertEqual(allocation["skipped_customer_ids"], [no_snapshot])
        by_id = {row["customer_id"]: row for row in allocation["decisions"]}
        self.assertEqual(by_id[high_value]["intervention_code"], "NO_OFFER")
        self.assertEqual(by_id[medium_value]["intervention_code"], "SMALL_DISCOUNT")
        self.assertEqual(by_id[medium_value]["historical_revenue"], 1000)
        self.assertEqual(by_id[low_risk]["intervention_code"], "NO_OFFER")
        self.assertEqual(body["customers_without_feature_snapshot"], [no_snapshot])
        self.assertEqual(body["customers_with_predictions"], 3)
        self.assertEqual(body["customers_with_offers"], 1)
        self.assertEqual(body["customers_with_no_offer"], 2)

        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 3)
            self.assertEqual(session.query(RetentionIntervention).count(), 3)
            setting = session.get(RetentionBudgetSetting, 1)
            self.assertEqual(setting.last_allocation["initial_budget"], 100)
            self.assertEqual(setting.last_allocation["remaining_budget"], 0)

        # Saving a different budget must not silently change saved decisions.
        before = body["latest_allocation"]
        self.client.put("/admin/budget", headers=headers, json={"total_budget": 350})
        after_save = self.client.get("/admin/dashboard", headers=headers).json()
        self.assertEqual(after_save["latest_allocation"], before)
        self.assertEqual(after_save["current_budget"], 350)

    def test_bulk_evaluation_preserves_offers_allocates_budget_and_persists_summary(self) -> None:
        active_customer = self.add_customer("bulk-active@example.test", revenue="400.00")
        redeemed_customer = self.add_customer("bulk-redeemed@example.test", revenue="600.00")
        new_offer_customer = self.add_customer("bulk-new@example.test", revenue="1200.00")
        low_risk_customer = self.add_customer("bulk-low@example.test", revenue="200.00")
        missing_customer = self.add_customer(
            "bulk-missing@example.test", revenue="100.00", snapshot=False
        )
        self.client.app.state.inference_service.probabilities = {
            active_customer: 0.8,
            redeemed_customer: 0.7,
            new_offer_customer: 0.5,
            low_risk_customer: 0.2,
        }

        with Session(self.engine) as session:
            free_shipping = session.scalar(
                select(Offer).where(Offer.code == "FREE_SHIPPING")
            )
            active = RetentionIntervention(
                user_id=active_customer,
                offer_id=free_shipping.id,
                intervention_cost=Decimal("60.00"),
                priority_score=Decimal("320.00"),
                decision_reason="existing demo offer",
                status="active",
            )
            redeemed = RetentionIntervention(
                user_id=redeemed_customer,
                offer_id=free_shipping.id,
                intervention_cost=Decimal("60.00"),
                priority_score=Decimal("420.00"),
                decision_reason="redeemed demo offer",
                status="active",
            )
            session.add_all([active, redeemed])
            session.flush()
            active_intervention_id = active.id
            session.add(
                RetentionOfferValidity(
                    intervention_id=active.id,
                    expires_at=utc_now() + timedelta(days=7),
                )
            )
            order = Order(
                user_id=redeemed_customer,
                total_amount=Decimal("20.00"),
                status="completed",
            )
            session.add(order)
            session.flush()
            session.add(
                RetentionOfferRedemption(
                    intervention_id=redeemed.id,
                    offer_id=free_shipping.id,
                    order_id=order.id,
                    discount_amount=Decimal("0.00"),
                    shipping_discount=Decimal("20.00"),
                    free_shipping_applied=True,
                )
            )
            session.add(RetentionBudgetSetting(id=1, total_budget=Decimal("300.00")))
            product = Product(
                name="Bulk evaluation test product",
                category="Test",
                price=Decimal("100.00"),
                stock=10,
            )
            session.add(product)
            session.flush()
            demo_product_id = product.id
            session.commit()

        headers = self.admin_headers()
        first = self.client.post(
            "/admin/retention/evaluate-all",
            headers=headers,
            json={"eligibility_threshold": 0.30},
        )
        self.assertEqual(first.status_code, 200, first.text)
        dashboard = first.json()
        summary = dashboard["latest_allocation"]
        self.assertEqual(summary["eligibility_threshold"], 0.30)
        self.assertEqual(summary["total_accounts"], 5)
        self.assertEqual(summary["customers_evaluated"], 4)
        self.assertEqual(summary["customers_missing_feature_snapshot"], 1)
        self.assertEqual(summary["customers_below_threshold"], 1)
        self.assertEqual(summary["customers_eligible"], 3)
        self.assertEqual(summary["existing_offers_preserved"], 2)
        self.assertEqual(summary["existing_redeemed_offers_preserved"], 1)
        self.assertEqual(summary["new_offers_generated"], 1)
        self.assertEqual(summary["total_new_offer_cost"], 100)
        self.assertEqual(summary["total_estimated_budget_allocated"], 220)
        self.assertEqual(summary["total_committed_reserved_cost"], 220)
        self.assertEqual(summary["remaining_budget"], 80)
        self.assertEqual(summary["skipped_customer_ids"], [missing_customer])
        rows = {row["customer_id"]: row for row in summary["decisions"]}
        self.assertEqual(rows[active_customer]["status"], "preserved_active")
        self.assertTrue(rows[active_customer]["preserved_existing_offer"])
        self.assertEqual(rows[redeemed_customer]["status"], "preserved_redeemed")
        self.assertTrue(rows[redeemed_customer]["preserved_redeemed_offer"])
        self.assertEqual(rows[new_offer_customer]["intervention_code"], "SMALL_DISCOUNT")
        self.assertEqual(rows[low_risk_customer]["intervention_code"], "NO_OFFER")
        self.assertFalse(rows[missing_customer]["has_feature_snapshot"])
        self.assertEqual(rows[missing_customer]["status"], "missing_feature_data")
        self.assertIsNone(rows[missing_customer]["churn_probability"])

        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 4)
            history = session.scalars(select(RetentionIntervention)).all()
            self.assertEqual(len(history), 4)
            self.assertEqual(
                session.get(RetentionBudgetSetting, 1).total_budget,
                Decimal("300.00"),
            )
            self.assertEqual(
                session.get(RetentionIntervention, active_intervention_id).status,
                "active",
            )
            self.assertIsNotNone(
                session.get(RetentionOfferRedemption, 1)
            )

        # A repeat refreshes predictions but protects already assigned paid
        # offers and cannot consume the same budget a second time.
        second = self.client.post(
            "/admin/retention/evaluate-all",
            headers=headers,
            json={"eligibility_threshold": 0.30},
        )
        self.assertEqual(second.status_code, 200, second.text)
        repeated = second.json()["latest_allocation"]
        self.assertEqual(repeated["new_offers_generated"], 0)
        self.assertEqual(repeated["total_committed_reserved_cost"], 220)
        self.assertEqual(repeated["remaining_budget"], 80)
        with Session(self.engine) as session:
            paid_active = session.execute(
                select(RetentionIntervention, Offer)
                .join(Offer, Offer.id == RetentionIntervention.offer_id)
                .where(
                    RetentionIntervention.status == "active",
                    Offer.code != "NO_OFFER",
                )
            ).all()
            self.assertEqual(len(paid_active), 3)
            self.assertEqual(
                len(
                    session.scalars(
                        select(RetentionIntervention).where(
                            RetentionIntervention.user_id == new_offer_customer,
                            RetentionIntervention.status == "active",
                        )
                    ).all()
                ),
                1,
            )

        with Session(self.engine) as session:
            new_intervention = session.scalar(
                select(RetentionIntervention).where(
                    RetentionIntervention.user_id == new_offer_customer,
                    RetentionIntervention.status == "active",
                )
            )
            self.assertIsNotNone(new_intervention)
            validity = session.scalar(
                select(RetentionOfferValidity).where(
                    RetentionOfferValidity.intervention_id == new_intervention.id
                )
            )
            self.assertIsNotNone(validity)
            self.assertGreater(validity.expires_at, utc_now())

        customer_headers = {
            "Authorization": f"Bearer {create_access_token(new_offer_customer, self.secret)}"
        }
        claim = self.client.post(
            "/retention/offer/claim", headers=customer_headers
        )
        self.assertEqual(claim.status_code, 201, claim.text)
        checkout = self.client.post(
            "/orders/checkout",
            headers=customer_headers,
            json={
                "items": [{"product_id": demo_product_id, "quantity": 1}],
                "apply_retention_offer": True,
            },
        )
        self.assertEqual(checkout.status_code, 201, checkout.text)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionOfferRedemption).count(), 2)

    def test_bulk_evaluation_rolls_back_if_inference_fails(self) -> None:
        self.add_customer("bulk-failure@example.test", revenue="10.00")
        with Session(self.engine) as session:
            session.add(RetentionBudgetSetting(id=1, total_budget=Decimal("500.00")))
            session.commit()
        self.client_context.__exit__(None, None, None)
        app = create_app(
            database_engine=self.engine,
            inference_service=FailingInferenceService(),
            auth_secret_key=self.secret,
            admin_email=ADMIN_EMAIL,
            admin_password_hash=self.password_hash,
        )
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        response = self.client.post(
            "/admin/retention/evaluate-all",
            headers=self.admin_headers(),
            json={"eligibility_threshold": 0.1},
        )
        self.assertEqual(response.status_code, 500)
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionPrediction).count(), 0)
            self.assertEqual(session.query(RetentionIntervention).count(), 0)
            self.assertIsNone(session.get(RetentionBudgetSetting, 1).last_allocation)

    def test_budget_reallocation_supersedes_previous_active_offer_in_history(self) -> None:
        self.add_customer("high@example.test", revenue="3000.00")
        self.add_customer("medium@example.test", revenue="1000.00")
        headers = self.admin_headers()
        self.client.put("/admin/budget", headers=headers, json={"total_budget": 100})
        first = self.client.post("/admin/retention/allocate", headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.client.put("/admin/budget", headers=headers, json={"total_budget": 350})
        with Session(self.engine) as session:
            before_rerun = session.scalars(
                select(RetentionIntervention).where(
                    RetentionIntervention.status == "active"
                )
            ).all()
            self.assertEqual(len(before_rerun), 1)
        second = self.client.post("/admin/retention/allocate", headers=headers)
        self.assertEqual(second.status_code, 200, second.text)
        rows = {row["customer_id"]: row for row in second.json()["latest_allocation"]["decisions"]}
        self.assertEqual(rows[1]["intervention_code"], "LARGE_DISCOUNT")
        self.assertEqual(rows[2]["intervention_code"], "SMALL_DISCOUNT")
        with Session(self.engine) as session:
            history = session.scalars(
                select(RetentionIntervention).where(RetentionIntervention.user_id == 2)
            ).all()
            self.assertEqual(len(history), 2)
            self.assertEqual({row.status for row in history}, {"active", "superseded"})

    def test_dashboard_left_joins_every_customer_and_marks_missing_records(self) -> None:
        ids = [
            self.add_customer(f"unseen{index}@example.test", revenue="0", snapshot=index != 3)
            for index in range(1, 4)
        ]
        with Session(self.engine) as session:
            session.add(
                RetentionPrediction(
                    user_id=ids[0],
                    churn_probability=Decimal("0.4400"),
                    customer_value=Decimal("0.00"),
                    model_version="test-model",
                )
            )
            no_offer = session.scalar(select(Offer).where(Offer.code == "NO_OFFER"))
            session.add(
                RetentionIntervention(
                    user_id=ids[1],
                    offer_id=no_offer.id,
                    intervention_cost=Decimal("0.00"),
                    priority_score=Decimal("0.0000"),
                    decision_reason="not evaluated prediction case",
                    status="no_offer",
                )
            )
            session.commit()
        response = self.client.get("/admin/dashboard", headers=self.admin_headers())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total_customers"], 3)
        self.assertEqual(len(body["current_decisions"]), 3)
        by_id = {row["customer_id"]: row for row in body["current_decisions"]}
        self.assertEqual(by_id[ids[0]]["churn_probability"], 0.44)
        self.assertIsNone(by_id[ids[0]]["intervention_code"])
        self.assertIsNone(by_id[ids[1]]["churn_probability"])
        self.assertEqual(by_id[ids[1]]["intervention_code"], "NO_OFFER")
        self.assertIsNone(by_id[ids[2]]["churn_probability"])
        self.assertIsNone(by_id[ids[2]]["intervention_code"])
        for customer_id in ids:
            self.assertEqual(by_id[customer_id]["customer_email"], f"unseen{customer_id}@example.test")
        self.assertFalse(by_id[ids[2]]["has_feature_snapshot"])
        self.assertIsNone(body["latest_allocation"])

    def test_dashboard_returns_all_nine_demo_accounts_and_other_customer_accounts(self) -> None:
        demo_ids = [
            self.add_customer(
                f"customer{index:02d}@demo.customer-retention.local", revenue="0"
            )
            for index in range(1, 10)
        ]
        unrelated_id = self.add_customer("registered@example.test", revenue="0")
        response = self.client.get("/admin/dashboard", headers=self.admin_headers())
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()["current_decisions"]
        self.assertEqual(len(rows), 10)
        self.assertEqual(response.json()["total_customers"], 10)
        by_id = {row["customer_id"]: row for row in rows}
        self.assertEqual(set(demo_ids) | {unrelated_id}, set(by_id))
        for customer_id in demo_ids:
            self.assertIn("@demo.customer-retention.local", by_id[customer_id]["customer_email"])
            self.assertIsNone(by_id[customer_id]["churn_probability"])
            self.assertIsNone(by_id[customer_id]["intervention_code"])

    def test_dashboard_retains_redemption_details_for_latest_intervention(self) -> None:
        customer_id = self.add_customer("redeemed-dashboard@example.test", revenue="0")
        with Session(self.engine) as session:
            offer = session.scalar(select(Offer).where(Offer.code == "FREE_SHIPPING"))
            order = Order(
                user_id=customer_id,
                total_amount=Decimal("20.00"),
                status="completed",
            )
            session.add(order)
            session.flush()
            intervention = RetentionIntervention(
                user_id=customer_id,
                offer_id=offer.id,
                intervention_cost=Decimal("60.00"),
                priority_score=Decimal("25.0000"),
                decision_reason="redeemed offer",
                status="active",
            )
            session.add(intervention)
            session.flush()
            session.add(
                RetentionOfferRedemption(
                    intervention_id=intervention.id,
                    offer_id=offer.id,
                    order_id=order.id,
                    discount_amount=Decimal("0.00"),
                    shipping_discount=Decimal("60.00"),
                    free_shipping_applied=True,
                )
            )
            session.commit()
            order_id = order.id
        response = self.client.get("/admin/dashboard", headers=self.admin_headers())
        row = response.json()["current_decisions"][0]
        self.assertEqual(row["claim_status"], "redeemed")
        self.assertEqual(row["redeemed_order_id"], order_id)
        self.assertTrue(row["free_shipping_applied"])

    def test_selected_evaluation_uses_model_result_threshold_and_persists_once(self) -> None:
        high_value = self.add_customer("live-high@example.test", revenue="3000.00")
        medium = self.add_customer("live-medium@example.test", revenue="1000.00")
        headers = self.admin_headers()
        self.client.put("/admin/budget", headers=headers, json={"total_budget": 500})

        eligible = self.client.post(
            f"/admin/customers/{high_value}/evaluate",
            headers=headers,
            json={"eligibility_threshold": 0.79},
        )
        self.assertEqual(eligible.status_code, 200, eligible.text)
        outcome = eligible.json()
        self.assertEqual(outcome["churn_probability"], 0.8)
        self.assertEqual(outcome["eligibility_threshold"], 0.79)
        self.assertTrue(outcome["eligible"])
        self.assertEqual(outcome["intervention_code"], "LARGE_DISCOUNT")
        self.assertEqual(outcome["estimated_intervention_cost"], 250)
        self.assertEqual(outcome["budget_available"], 500)
        self.assertEqual(outcome["budget_remaining"], 250)
        self.assertTrue(outcome["budget_allowed_assignment"])

        duplicate = self.client.post(
            f"/admin/customers/{high_value}/evaluate",
            headers=headers,
            json={"eligibility_threshold": 0.10},
        )
        self.assertEqual(duplicate.status_code, 409)
        below_threshold = self.client.post(
            f"/admin/customers/{medium}/evaluate",
            headers=headers,
            json={"eligibility_threshold": 0.51},
        )
        self.assertEqual(below_threshold.status_code, 200, below_threshold.text)
        self.assertFalse(below_threshold.json()["eligible"])
        self.assertEqual(below_threshold.json()["intervention_code"], "NO_OFFER")

        with Session(self.engine) as session:
            self.assertEqual(
                session.query(RetentionPrediction).filter_by(user_id=high_value).count(), 1
            )
            assigned = session.scalars(
                select(RetentionIntervention).where(
                    RetentionIntervention.user_id == high_value
                )
            ).all()
            self.assertEqual(len(assigned), 1)
            self.assertEqual(assigned[0].status, "active")
            self.assertEqual(
                session.query(RetentionPrediction).filter_by(user_id=medium).count(), 1
            )

    def test_generated_offer_is_customer_scoped_claimable_and_redeemable_at_checkout(self) -> None:
        selected = self.add_customer("live-owner@example.test", revenue="3000.00")
        other = self.add_customer("live-other@example.test", revenue="0")
        customer_password = "owner-password-for-test"
        with Session(self.engine) as session:
            session.get(User, selected).password_hash = hash_password(customer_password)
            product = Product(
                name="Test grocery",
                description="",
                category="Test",
                price=Decimal("3000.00"),
                stock=5,
            )
            session.add(product)
            session.commit()
            product_id = product.id
        admin_headers = self.admin_headers()
        self.client.put("/admin/budget", headers=admin_headers, json={"total_budget": 500})
        evaluated = self.client.post(
            f"/admin/customers/{selected}/evaluate",
            headers=admin_headers,
            json={"eligibility_threshold": 0.30},
        )
        self.assertEqual(evaluated.status_code, 200, evaluated.text)
        self.assertEqual(evaluated.json()["intervention_code"], "LARGE_DISCOUNT")

        login = self.client.post(
            "/auth/login",
            json={"email": "live-owner@example.test", "password": customer_password},
        )
        self.assertEqual(login.status_code, 200, login.text)
        owner_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assigned = self.client.get("/retention/offer", headers=owner_headers)
        self.assertTrue(assigned.json()["assigned"])
        self.assertEqual(
            assigned.json()["intervention"]["offer"]["name"],
            "Your LittleLeaf discount",
        )
        self.assertEqual(
            assigned.json()["intervention"]["offer"]["discount_percentage"], 10
        )

        with Session(self.engine) as session:
            session.get(User, other).password_hash = hash_password("other-password-for-test")
            session.commit()
        other_login = self.client.post(
            "/auth/login",
            json={"email": "live-other@example.test", "password": "other-password-for-test"},
        )
        self.assertEqual(other_login.status_code, 200, other_login.text)
        other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
        self.assertEqual(
            self.client.get("/retention/offer", headers=other_headers).json(),
            {"assigned": False, "intervention": None},
        )

        claimed = self.client.post("/retention/offer/claim", headers=owner_headers)
        self.assertEqual(claimed.status_code, 201, claimed.text)
        checkout = self.client.post(
            "/orders/checkout",
            headers=owner_headers,
            json={
                "items": [{"product_id": product_id, "quantity": 1}],
                "apply_retention_offer": True,
            },
        )
        self.assertEqual(checkout.status_code, 201, checkout.text)
        self.assertEqual(checkout.json()["pricing"]["applied_offer_name"], "Large discount")
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionOfferRedemption).count(), 1)

    def test_selected_evaluation_reserves_existing_cost_and_keeps_redemption(self) -> None:
        reserved_customer = self.add_customer("reserved@example.test", revenue="0")
        selected = self.add_customer("selected@example.test", revenue="1000.00")
        headers = self.admin_headers()
        self.client.put("/admin/budget", headers=headers, json={"total_budget": 100})
        with Session(self.engine) as session:
            free_shipping = session.scalar(select(Offer).where(Offer.code == "FREE_SHIPPING"))
            active = RetentionIntervention(
                user_id=reserved_customer,
                offer_id=free_shipping.id,
                intervention_cost=Decimal("60.00"),
                priority_score=Decimal("10.0000"),
                decision_reason="existing assignment",
                status="active",
            )
            session.add(active)
            session.commit()

        result = self.client.post(
            f"/admin/customers/{selected}/evaluate",
            headers=headers,
            json={"eligibility_threshold": 0.30},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["budget_available"], 40)
        self.assertEqual(result.json()["intervention_code"], "NO_OFFER")
        self.assertFalse(result.json()["budget_allowed_assignment"])

        redeemed_customer = self.add_customer("redeemed@example.test", revenue="500.00")
        with Session(self.engine) as session:
            offer = session.scalar(select(Offer).where(Offer.code == "FREE_SHIPPING"))
            order = Order(
                user_id=redeemed_customer,
                total_amount=Decimal("50.00"),
                status="completed",
            )
            session.add(order)
            session.flush()
            redeemed = RetentionIntervention(
                user_id=redeemed_customer,
                offer_id=offer.id,
                intervention_cost=Decimal("60.00"),
                priority_score=Decimal("20.0000"),
                decision_reason="already redeemed",
                status="active",
            )
            session.add(redeemed)
            session.flush()
            redemption = RetentionOfferRedemption(
                intervention_id=redeemed.id,
                offer_id=offer.id,
                order_id=order.id,
                discount_amount=Decimal("0.00"),
                shipping_discount=Decimal("60.00"),
                free_shipping_applied=True,
            )
            session.add(redemption)
            session.commit()
            redeemed_intervention_id = redeemed.id

        rejected = self.client.post(
            f"/admin/customers/{redeemed_customer}/evaluate",
            headers=headers,
            json={"eligibility_threshold": 0.10},
        )
        self.assertEqual(rejected.status_code, 409)
        with Session(self.engine) as session:
            preserved = session.get(RetentionIntervention, redeemed_intervention_id)
            self.assertEqual(preserved.status, "active")
            self.assertIsNotNone(preserved.redemption)
            self.assertEqual(
                session.query(RetentionPrediction).filter_by(user_id=redeemed_customer).count(),
                0,
            )

    def test_evaluation_threshold_bounds_and_budget_skip(self) -> None:
        customer_id = self.add_customer("limited@example.test", revenue="3000.00")
        headers = self.admin_headers()
        self.client.put("/admin/budget", headers=headers, json={"total_budget": 100})
        invalid = self.client.post(
            f"/admin/customers/{customer_id}/evaluate",
            headers=headers,
            json={"eligibility_threshold": 0.09},
        )
        self.assertEqual(invalid.status_code, 422)
        skipped = self.client.post(
            f"/admin/customers/{customer_id}/evaluate",
            headers=headers,
            json={"eligibility_threshold": 0.80},
        )
        self.assertEqual(skipped.status_code, 200, skipped.text)
        self.assertTrue(skipped.json()["eligible"])
        self.assertEqual(skipped.json()["intervention_code"], "NO_OFFER")
        self.assertFalse(skipped.json()["budget_allowed_assignment"])
        self.assertEqual(skipped.json()["budget_remaining"], 100)


if __name__ == "__main__":
    unittest.main()
