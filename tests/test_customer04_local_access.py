"""Customer 04 local password setup must only change that seeded account."""

from datetime import timedelta
from decimal import Decimal
import secrets
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import hash_password, verify_password
from api.main import create_app
from database.base import utc_now
from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import (
    CustomerActivity,
    Offer,
    Order,
    RetentionIntervention,
    RetentionOfferClaim,
    RetentionOfferRedemption,
    RetentionOfferValidity,
    RetentionPrediction,
    User,
)
from scripts.configure_demo_customer_access import DEMO_CUSTOMER_04
from scripts.configure_local_demo import configure_local_customer04_password
from scripts.seed_demo_data import seed_demo_data
from tests.test_admin_api import FakeInferenceService


class Customer04LocalAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "customer04-access.db"
        self.engine = create_database_engine(f"sqlite:///{path.as_posix()}")
        initialize_database(self.engine)
        seed_demo_data(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp_directory.cleanup()

    def test_password_reset_isolated_and_existing_customer_offer_still_works(self) -> None:
        password01 = "Customer01-test-pass"
        password02 = "Customer02-test-pass"
        password04 = "Customer04-new-pass"
        with Session(self.engine) as session:
            customer01 = session.scalar(
                select(User).where(User.email == "customer01@demo.customer-retention.local")
            )
            customer02 = session.scalar(
                select(User).where(User.email == "customer02@demo.customer-retention.local")
            )
            customer04 = session.scalar(
                select(User).where(User.email == DEMO_CUSTOMER_04)
            )
            customer01.password_hash = hash_password(password01)
            customer02.password_hash = hash_password(password02)
            discount = session.scalar(
                select(Offer).where(Offer.code == "SMALL_DISCOUNT")
            )
            shipping = session.scalar(
                select(Offer).where(Offer.code == "FREE_SHIPPING")
            )
            interventions = [
                RetentionIntervention(
                    user_id=customer04.id,
                    offer_id=discount.id,
                    intervention_cost=discount.maximum_cost,
                    priority_score=Decimal("75.00"),
                    decision_reason="existing Customer 04 offer",
                    status="active",
                ),
                RetentionIntervention(
                    user_id=customer01.id,
                    offer_id=shipping.id,
                    intervention_cost=shipping.maximum_cost,
                    priority_score=Decimal("25.00"),
                    decision_reason="separate Customer 01 offer",
                    status="active",
                ),
            ]
            session.add_all(interventions)
            session.flush()
            c04_intervention_id, c01_intervention_id = [row.id for row in interventions]
            session.add_all(
                [
                    RetentionOfferValidity(
                        intervention_id=c04_intervention_id,
                        expires_at=utc_now() + timedelta(days=7),
                    ),
                    RetentionOfferValidity(
                        intervention_id=c01_intervention_id,
                        expires_at=utc_now() + timedelta(days=7),
                    ),
                ]
            )
            session.commit()

        with Session(self.engine) as session:
            before_users = {
                user.email: (user.id, user.role, user.password_hash)
                for user in session.scalars(select(User)).all()
            }
            before_counts = (
                session.scalar(select(func.count()).select_from(Order)),
                session.scalar(select(func.count()).select_from(CustomerActivity)),
                session.scalar(select(func.count()).select_from(RetentionPrediction)),
                session.scalar(select(func.count()).select_from(RetentionIntervention)),
                session.scalar(select(func.count()).select_from(RetentionOfferValidity)),
                session.scalar(select(func.count()).select_from(RetentionOfferClaim)),
                session.scalar(select(func.count()).select_from(RetentionOfferRedemption)),
            )

        configure_local_customer04_password(self.engine, password04)

        with Session(self.engine) as session:
            after_users = {
                user.email: (user.id, user.role, user.password_hash)
                for user in session.scalars(select(User)).all()
            }
            after_counts = (
                session.scalar(select(func.count()).select_from(Order)),
                session.scalar(select(func.count()).select_from(CustomerActivity)),
                session.scalar(select(func.count()).select_from(RetentionPrediction)),
                session.scalar(select(func.count()).select_from(RetentionIntervention)),
                session.scalar(select(func.count()).select_from(RetentionOfferValidity)),
                session.scalar(select(func.count()).select_from(RetentionOfferClaim)),
                session.scalar(select(func.count()).select_from(RetentionOfferRedemption)),
            )
            saved_c04_hash = after_users[DEMO_CUSTOMER_04][2]
            self.assertEqual(
                session.get(RetentionIntervention, c04_intervention_id).status,
                "active",
            )
        self.assertTrue(verify_password(password04, saved_c04_hash))
        self.assertNotEqual(saved_c04_hash, password04)
        self.assertEqual(set(before_users), set(after_users))
        for email, previous in before_users.items():
            if email == DEMO_CUSTOMER_04:
                self.assertEqual(previous[:2], after_users[email][:2])
                self.assertNotEqual(previous[2], after_users[email][2])
            else:
                self.assertEqual(previous, after_users[email])
        self.assertEqual(before_counts, after_counts)

        admin_password = "Admin-test-only-password"
        app = create_app(
            database_engine=self.engine,
            inference_service=FakeInferenceService(),
            auth_secret_key=secrets.token_urlsafe(48),
            admin_email="admin@littleleaf.local",
            admin_password_hash=hash_password(admin_password),
        )
        with TestClient(app) as client:
            login04 = client.post(
                "/auth/login",
                json={"email": DEMO_CUSTOMER_04, "password": password04},
            )
            self.assertEqual(login04.status_code, 200)
            headers04 = {"Authorization": f"Bearer {login04.json()['access_token']}"}
            offer04 = client.get("/retention/offer", headers=headers04)
            self.assertEqual(offer04.status_code, 200)
            self.assertTrue(offer04.json()["assigned"])
            self.assertEqual(
                offer04.json()["intervention"]["offer"]["discount_percentage"], 5
            )
            self.assertEqual(client.get("/admin/dashboard", headers=headers04).status_code, 401)

            login01 = client.post(
                "/auth/login",
                json={
                    "email": "customer01@demo.customer-retention.local",
                    "password": password01,
                },
            )
            self.assertEqual(login01.status_code, 200)
            headers01 = {"Authorization": f"Bearer {login01.json()['access_token']}"}
            offer01 = client.get("/retention/offer", headers=headers01)
            self.assertEqual(offer01.status_code, 200)
            self.assertEqual(
                offer01.json()["intervention"]["offer"]["name"], "Free shipping"
            )
            self.assertNotEqual(
                offer01.json()["intervention"]["offer"]["name"],
                offer04.json()["intervention"]["offer"]["name"],
            )

            login02 = client.post(
                "/auth/login",
                json={
                    "email": "customer02@demo.customer-retention.local",
                    "password": password02,
                },
            )
            self.assertEqual(login02.status_code, 200)
            headers02 = {"Authorization": f"Bearer {login02.json()['access_token']}"}
            offer02 = client.get("/retention/offer", headers=headers02)
            self.assertEqual(offer02.status_code, 200)
            self.assertFalse(offer02.json()["assigned"])
            self.assertEqual(client.get("/admin/dashboard", headers=headers02).status_code, 401)

            admin_login = client.post(
                "/admin/auth/login",
                json={"email": "admin@littleleaf.local", "password": admin_password},
            )
            self.assertEqual(admin_login.status_code, 200)
            admin_headers = {
                "Authorization": f"Bearer {admin_login.json()['access_token']}"
            }
            self.assertEqual(client.get("/admin/dashboard", headers=admin_headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
