"""Repeatability and preservation tests for the explicit demo order seeder."""

from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import (
    CustomerActivity,
    Order,
    Product,
    RetentionIntervention,
    RetentionPrediction,
    User,
)
from scripts.seed_demo_data import DEMO_EMAIL_DOMAIN, seed_demo_data
from scripts.seed_demo_order_histories import (
    ORDER_MARKER_EVENT_TYPE,
    ORDER_MARKER_NAMESPACE,
    seed_demo_order_histories,
)
from scripts.seed_store_products import seed_store_products


class DemoOrderHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "demo-orders.db"
        self.engine = create_database_engine(f"sqlite:///{path.as_posix()}")
        initialize_database(self.engine)
        seed_store_products(self.engine)
        seed_demo_data(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temp.cleanup()

    def _customer_history(self, email: str):
        with Session(self.engine) as session:
            user = session.scalar(select(User).where(User.email == email))
            orders = session.scalars(
                select(Order).where(Order.user_id == user.id).order_by(Order.id)
            ).all()
            return [
                (
                    order.id,
                    order.user_id,
                    order.total_amount,
                    order.status,
                    order.created_at,
                    tuple(
                        (line.product_id, line.quantity, line.unit_price)
                        for line in order.items
                    ),
                )
                for order in orders
            ]

    def test_orders_are_varied_completed_idempotent_and_preserve_customer01_02(self) -> None:
        first_two = {
            number: self._customer_history(f"customer{number:02d}@{DEMO_EMAIL_DOMAIN}")
            for number in (1, 2)
        }
        with Session(self.engine) as session:
            catalogue_before = {
                product.id: (product.name, product.price, product.stock)
                for product in session.scalars(select(Product)).all()
            }
            customer_ids = {
                user.email: user.id
                for user in session.scalars(
                    select(User).where(
                        User.email.in_(
                            [f"customer{number:02d}@{DEMO_EMAIL_DOMAIN}" for number in range(1, 10)]
                        )
                    )
                ).all()
            }
            features_before = {
                email: session.scalars(
                    select(CustomerActivity.event_metadata).where(
                        CustomerActivity.user_id == user_id,
                        CustomerActivity.event_type == "model_features_snapshot",
                    )
                ).all()
                for email, user_id in customer_ids.items()
            }
            prediction_count_before = session.scalar(
                select(func.count()).select_from(RetentionPrediction)
            )
            intervention_count_before = session.scalar(
                select(func.count()).select_from(RetentionIntervention)
            )

        first = seed_demo_order_histories(self.engine)
        self.assertEqual(
            {email.split("customer")[1][:2]: values["new_orders"] for email, values in first.items()},
            {"03": 2, "04": 1, "05": 2, "06": 0, "07": 2, "08": 1, "09": 1},
        )

        second = seed_demo_order_histories(self.engine)
        self.assertTrue(all(values["new_orders"] == 0 for values in second.values()))
        for email in first:
            self.assertEqual(first[email]["completed_orders"], second[email]["completed_orders"])
            self.assertEqual(first[email]["historical_revenue"], second[email]["historical_revenue"])

        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(CustomerActivity).where(
                        CustomerActivity.event_type == ORDER_MARKER_EVENT_TYPE
                    )
                ),
                9,
            )
            marked_rows = session.scalars(
                select(CustomerActivity).where(
                    CustomerActivity.event_type == ORDER_MARKER_EVENT_TYPE
                )
            ).all()
            self.assertTrue(
                all(row.event_metadata["namespace"] == ORDER_MARKER_NAMESPACE for row in marked_rows)
            )
            for row in marked_rows:
                order = session.get(Order, row.event_metadata["order_id"])
                self.assertEqual(order.user_id, row.user_id)
                self.assertEqual(order.status, "completed")
                self.assertGreater(len(order.items), 0)
                self.assertEqual(
                    sum((line.unit_price * line.quantity for line in order.items), Decimal("0.00")),
                    order.total_amount,
                )

            customer06_id = session.scalar(
                select(User.id).where(User.email == f"customer06@{DEMO_EMAIL_DOMAIN}")
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Order).where(Order.user_id == customer06_id)),
                0,
            )
            catalogue_after = {
                product.id: (product.name, product.price, product.stock)
                for product in session.scalars(select(Product)).all()
            }
            self.assertEqual(catalogue_before, catalogue_after)
            features_after = {
                email: session.scalars(
                    select(CustomerActivity.event_metadata).where(
                        CustomerActivity.user_id == user_id,
                        CustomerActivity.event_type == "model_features_snapshot",
                    )
                ).all()
                for email, user_id in customer_ids.items()
            }
            self.assertEqual(features_before, features_after)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(RetentionPrediction)),
                prediction_count_before,
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(RetentionIntervention)),
                intervention_count_before,
            )

        for number in (1, 2):
            self.assertEqual(
                self._customer_history(f"customer{number:02d}@{DEMO_EMAIL_DOMAIN}"),
                first_two[number],
            )


if __name__ == "__main__":
    unittest.main()
