"""Unit tests for database initialization and persistence."""

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.initialize import APPROVED_OFFERS, initialize_database
from database.models import (
    CustomerActivity,
    Offer,
    Order,
    OrderItem,
    Product,
    RetentionIntervention,
    RetentionPrediction,
    User,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite:///:memory:")

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_initialization_creates_tables_and_is_idempotent(self) -> None:
        initialize_database(self.engine)
        initialize_database(self.engine)

        with Session(self.engine) as session:
            offers = session.query(Offer).order_by(Offer.code).all()
            self.assertEqual(len(offers), 4)
            self.assertEqual(
                {offer.code for offer in offers},
                {offer["code"] for offer in APPROVED_OFFERS},
            )

    def test_approved_offer_costs_match_decision_engine_catalogue(self) -> None:
        initialize_database(self.engine)

        with Session(self.engine) as session:
            costs = {
                offer.code: offer.maximum_cost
                for offer in session.query(Offer).all()
            }

        self.assertEqual(
            costs,
            {
                "NO_OFFER": Decimal("0.00"),
                "SMALL_DISCOUNT": Decimal("100.00"),
                "LARGE_DISCOUNT": Decimal("250.00"),
                "FREE_SHIPPING": Decimal("60.00"),
            },
        )

    def test_sqlite_foreign_keys_are_enabled_and_enforced(self) -> None:
        initialize_database(self.engine)

        with self.engine.connect() as connection:
            enabled = connection.scalar(text("PRAGMA foreign_keys"))
        self.assertEqual(enabled, 1)

        with Session(self.engine) as session:
            session.add(
                Order(
                    user_id=999,
                    total_amount=Decimal("10.00"),
                    status="completed",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()

    def test_basic_insert_read_relationships_json_and_utc_timestamps(self) -> None:
        initialize_database(self.engine)

        with Session(self.engine) as session:
            user = User(
                name="Demo Customer",
                email="demo@example.test",
                password_hash="hashed-value",
                role="customer",
            )
            product = Product(
                name="Demo Product",
                description="For persistence testing",
                category="Demo",
                price=Decimal("499.00"),
                stock=5,
            )
            session.add_all([user, product])
            session.flush()

            order = Order(
                user_id=user.id,
                total_amount=Decimal("499.00"),
                status="completed",
            )
            session.add(order)
            session.flush()
            session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=1,
                    unit_price=Decimal("499.00"),
                )
            )
            session.add(
                CustomerActivity(
                    user_id=user.id,
                    event_type="product_viewed",
                    product_id=product.id,
                    event_metadata={"source": "test", "position": 2},
                )
            )
            prediction = RetentionPrediction(
                user_id=user.id,
                churn_probability=Decimal("0.4200"),
                customer_value=Decimal("499.00"),
                predicted_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
                model_version="baseline-v1",
            )
            session.add(prediction)
            offer = session.query(Offer).filter_by(code="SMALL_DISCOUNT").one()
            intervention = RetentionIntervention(
                user_id=user.id,
                offer_id=offer.id,
                intervention_cost=Decimal("100.00"),
                priority_score=Decimal("209.5800"),
                decision_reason="Database persistence test",
                status="assigned",
            )
            session.add(intervention)
            session.commit()

            loaded_user = session.get(User, user.id)
            loaded_order = session.get(Order, order.id)
            loaded_activity = session.query(CustomerActivity).one()
            loaded_prediction = session.query(RetentionPrediction).one()

            self.assertEqual(loaded_user.email, "demo@example.test")
            self.assertEqual(loaded_order.items[0].product.name, "Demo Product")
            self.assertEqual(
                loaded_activity.event_metadata,
                {"source": "test", "position": 2},
            )
            self.assertEqual(loaded_prediction.predicted_at.utcoffset().total_seconds(), 0)
            self.assertIsNotNone(loaded_user.created_at.tzinfo)


if __name__ == "__main__":
    unittest.main()
