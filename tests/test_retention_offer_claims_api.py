"""Isolated API tests for simulated retention offer claims."""

from datetime import timedelta
from decimal import Decimal
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
from database.base import utc_now
from database.models import (
    Offer,
    Order,
    Product,
    RetentionBudgetSetting,
    RetentionIntervention,
    RetentionOfferClaim,
    RetentionOfferValidity,
    RetentionPrediction,
    User,
)
from database.initialize import initialize_database


class RetentionOfferClaimApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_directory.name) / "offer-claims.db"
        self.engine = create_database_engine(f"sqlite:///{db_path.as_posix()}")
        self.secret = secrets.token_urlsafe(48)
        app = create_app(
            database_engine=self.engine,
            inference_service=None,
            auth_secret_key=self.secret,
            admin_email="admin@example.test",
            admin_password_hash=hash_password("valid-test-admin-password"),
        )
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.customer_id = self.add_customer("claim-owner@example.test")
        self.other_customer_id = self.add_customer("other-owner@example.test")
        self.intervention_id = self.add_intervention(self.customer_id)

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.engine.dispose()
        self.temp_directory.cleanup()

    def add_customer(self, email: str) -> int:
        with Session(self.engine) as session:
            user = User(
                name="Claim test customer",
                email=email,
                password_hash=hash_password("customer-password"),
                role="customer",
            )
            session.add(user)
            session.commit()
            return user.id

    def add_intervention(
        self,
        customer_id: int,
        *,
        status: str = "active",
        offer_active: bool = True,
        code: str = "FREE_SHIPPING",
    ) -> int:
        with Session(self.engine) as session:
            offer = session.scalar(select(Offer).where(Offer.code == code))
            offer.active = offer_active
            intervention = RetentionIntervention(
                user_id=customer_id,
                offer_id=offer.id,
                intervention_cost=Decimal("60.00" if code == "FREE_SHIPPING" else "100.00"),
                priority_score=Decimal("500.0000"),
                decision_reason="Test fixture only.",
                status=status,
            )
            session.add(intervention)
            session.flush()
            session.add(
                RetentionOfferValidity(
                    intervention_id=intervention.id,
                    expires_at=utc_now() + timedelta(days=7),
                )
            )
            session.commit()
            return intervention.id

    def headers(self, customer_id: int) -> dict[str, str]:
        token = create_access_token(customer_id, self.secret)
        return {"Authorization": f"Bearer {token}"}

    def admin_headers(self) -> dict[str, str]:
        response = self.client.post(
            "/admin/auth/login",
            json={"email": "admin@example.test", "password": "valid-test-admin-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_customer_claims_own_active_offer_and_offer_page_shows_timestamp(self) -> None:
        claimed = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(claimed.status_code, 201, claimed.text)
        self.assertTrue(claimed.json()["claimed"])
        self.assertIsNotNone(claimed.json()["claimed_at"])

        offer = self.client.get(
            "/retention/offer", headers=self.headers(self.customer_id)
        )
        self.assertEqual(offer.status_code, 200, offer.text)
        self.assertTrue(offer.json()["intervention"]["claimed"])
        self.assertEqual(
            offer.json()["intervention"]["claimed_at"], claimed.json()["claimed_at"]
        )

        other_offer = self.client.get(
            "/retention/offer", headers=self.headers(self.other_customer_id)
        )
        self.assertEqual(other_offer.json(), {"assigned": False, "intervention": None})

    def test_duplicate_claim_is_rejected_and_only_one_row_is_saved(self) -> None:
        headers = self.headers(self.customer_id)
        first = self.client.post("/retention/offer/claim", headers=headers)
        second = self.client.post("/retention/offer/claim", headers=headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertIn("already been claimed", second.json()["detail"])
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionOfferClaim).count(), 1)

    def test_no_active_offer_is_not_claimable(self) -> None:
        with Session(self.engine) as session:
            intervention = session.get(RetentionIntervention, self.intervention_id)
            intervention.offer_id = session.scalar(
                select(Offer.id).where(Offer.code == "NO_OFFER")
            )
            intervention.status = "no_offer"
            session.commit()
        response = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("No active assigned offer", response.json()["detail"])

    def test_customer_cannot_claim_another_customers_offer(self) -> None:
        with Session(self.engine) as session:
            session.get(RetentionIntervention, self.intervention_id).status = "superseded"
            session.commit()
        other_intervention_id = self.add_intervention(self.other_customer_id)

        response = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(response.status_code, 409)
        with Session(self.engine) as session:
            self.assertIsNone(
                session.scalar(
                    select(RetentionOfferClaim).where(
                        RetentionOfferClaim.intervention_id == other_intervention_id
                    )
                )
            )

    def test_claim_endpoint_requires_customer_authentication(self) -> None:
        response = self.client.post("/retention/offer/claim")
        self.assertEqual(response.status_code, 401)

    def test_superseded_offer_is_not_claimable(self) -> None:
        with Session(self.engine) as session:
            session.get(RetentionIntervention, self.intervention_id).status = "superseded"
            session.commit()
        response = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("no longer active", response.json()["detail"])

    def test_inactive_offer_is_not_claimable(self) -> None:
        with Session(self.engine) as session:
            session.get(RetentionIntervention, self.intervention_id).offer.active = False
            session.commit()
        response = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("no longer active", response.json()["detail"])

    def test_expired_offer_is_shown_as_expired_and_cannot_be_claimed(self) -> None:
        with Session(self.engine) as session:
            validity = session.scalar(
                select(RetentionOfferValidity).where(
                    RetentionOfferValidity.intervention_id == self.intervention_id
                )
            )
            validity.expires_at = utc_now() - timedelta(seconds=1)
            session.commit()

        offer = self.client.get(
            "/retention/offer", headers=self.headers(self.customer_id)
        )
        self.assertEqual(offer.status_code, 200, offer.text)
        assigned = offer.json()["intervention"]
        self.assertTrue(assigned["expired"])
        self.assertLessEqual(assigned["expires_at"], utc_now().isoformat())

        claim = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(claim.status_code, 409)
        self.assertEqual(claim.json()["detail"], "Your offer has expired.")
        with Session(self.engine) as session:
            self.assertEqual(session.query(RetentionOfferClaim).count(), 0)

    def test_existing_offer_expiry_backfill_is_idempotent(self) -> None:
        with Session(self.engine) as session:
            intervention = session.get(RetentionIntervention, self.intervention_id)
            intervention.created_at = utc_now() - timedelta(days=2)
            session.query(RetentionOfferValidity).filter_by(
                intervention_id=self.intervention_id
            ).delete()
            session.commit()

        initialize_database(self.engine, offer_validity_days=7)
        with Session(self.engine) as session:
            first_expiry = session.scalar(
                select(RetentionOfferValidity.expires_at).where(
                    RetentionOfferValidity.intervention_id == self.intervention_id
                )
            )
            assigned_at = session.get(RetentionIntervention, self.intervention_id).created_at
        self.assertEqual(first_expiry, assigned_at + timedelta(days=7))

        initialize_database(self.engine, offer_validity_days=30)
        with Session(self.engine) as session:
            second_expiry = session.scalar(
                select(RetentionOfferValidity.expires_at).where(
                    RetentionOfferValidity.intervention_id == self.intervention_id
                )
            )
        self.assertEqual(second_expiry, first_expiry)

    def test_customers_cannot_access_admin_claim_information(self) -> None:
        response = self.client.get(
            "/admin/dashboard", headers=self.headers(self.customer_id)
        )
        self.assertEqual(response.status_code, 401)

    def test_admin_dashboard_shows_claim_status(self) -> None:
        with Session(self.engine) as session:
            session.add(
                RetentionPrediction(
                    user_id=self.customer_id,
                    churn_probability=Decimal("0.8000"),
                    customer_value=Decimal("250.00"),
                    model_version="claim-test-model",
                )
            )
            session.commit()
        headers = self.admin_headers()
        before = self.client.get("/admin/dashboard", headers=headers)
        self.assertEqual(before.status_code, 200, before.text)
        before_row = before.json()["current_decisions"][0]
        self.assertEqual(before_row["claim_status"], "assigned")
        self.assertIsNone(before_row["claimed_at"])

        claimed = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(claimed.status_code, 201)
        after = self.client.get("/admin/dashboard", headers=headers)
        row = after.json()["current_decisions"][0]
        self.assertEqual(row["claim_status"], "claimed")
        self.assertEqual(row["claimed_at"], claimed.json()["claimed_at"])

        with Session(self.engine) as session:
            product = Product(
                name="Offer test product", category="Test", price=Decimal("10.00"), stock=2
            )
            session.add(product)
            session.commit()
            product_id = product.id
        order = self.client.post(
            "/orders/checkout",
            headers=self.headers(self.customer_id),
            json={"items": [{"product_id": product_id, "quantity": 1}], "apply_retention_offer": True},
        )
        self.assertEqual(order.status_code, 201, order.text)
        redeemed = self.client.get("/admin/dashboard", headers=headers)
        row = redeemed.json()["current_decisions"][0]
        self.assertEqual(row["claim_status"], "redeemed")
        self.assertEqual(row["redeemed_order_id"], order.json()["id"])
        self.assertEqual(row["redemption_discount_amount"], 0.0)
        self.assertEqual(row["redemption_shipping_discount"], 40.0)
        self.assertTrue(row["free_shipping_applied"])
        self.assertIsNotNone(row["redeemed_at"])
        customer_offer = self.client.get(
            "/retention/offer", headers=self.headers(self.customer_id)
        )
        self.assertTrue(customer_offer.json()["intervention"]["redeemed"])

    def test_claim_does_not_change_budget_intervention_cost_or_order_totals(self) -> None:
        with Session(self.engine) as session:
            intervention = session.get(RetentionIntervention, self.intervention_id)
            original_cost = intervention.intervention_cost
            session.add(
                RetentionBudgetSetting(
                    id=1,
                    total_budget=Decimal("500.00"),
                    last_allocation={"initial_budget": 500},
                )
            )
            session.add(
                Order(
                    user_id=self.customer_id,
                    total_amount=Decimal("125.00"),
                    status="completed",
                )
            )
            session.commit()

        response = self.client.post(
            "/retention/offer/claim", headers=self.headers(self.customer_id)
        )
        self.assertEqual(response.status_code, 201, response.text)
        with Session(self.engine) as session:
            self.assertEqual(
                session.get(RetentionIntervention, self.intervention_id).intervention_cost,
                original_cost,
            )
            setting = session.get(RetentionBudgetSetting, 1)
            self.assertEqual(setting.total_budget, Decimal("500.00"))
            self.assertEqual(setting.last_allocation, {"initial_budget": 500})
            self.assertEqual(
                session.scalar(select(Order.total_amount).where(Order.user_id == self.customer_id)),
                Decimal("125.00"),
            )


if __name__ == "__main__":
    unittest.main()
