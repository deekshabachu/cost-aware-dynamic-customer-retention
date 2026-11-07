"""Add repeatable simulated completed orders for demo customers 03–09.

Run manually with ``python -m scripts.seed_demo_order_histories``. The script
uses existing catalogue IDs/prices and the checkout order service. It never
creates accounts, changes existing orders, or runs during application startup.
Order IDs are marked in customer activity in the same transaction, so reruns
can identify exactly which orders this script created without a schema change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.base import utc_now
from database.config import create_database_engine
from database.models import CustomerActivity, Order, Product, User
from scripts.seed_demo_data import (
    DEMO_EMAIL_DOMAIN,
    DEMO_MANIFEST_EVENT_TYPE,
    DEMO_NAMESPACE,
)
from services.orders import SIMULATED_COMPLETED_STATUS, create_simulated_order


ORDER_MARKER_EVENT_TYPE = "demo_order_history_seed"
ORDER_MARKER_NAMESPACE = "littleleaf-demo-order-histories-v1"


@dataclass(frozen=True)
class PlannedOrder:
    days_ago: int
    lines: tuple[tuple[str, int], ...]


# Customer 06 deliberately remains order-free; its existing state already meets
# the no-order demo case, so no existing data needs to be removed.
ORDER_PLANS: dict[int, tuple[PlannedOrder, ...]] = {
    3: (
        PlannedOrder(25, (("Amul Taaza Toned Milk", 3), ("Amul Fresh Paneer", 2), ("Farm Fresh Eggs", 1))),
        PlannedOrder(5, (("Surf Excel Easy Wash", 1), ("Shimla Apples", 2))),
    ),
    4: (PlannedOrder(12, (("Mother Dairy Classic Curd", 2), ("Colgate Strong Teeth Toothpaste", 1), ("Harvest Gold White Bread", 1))),),
    5: (
        PlannedOrder(21, (("Real Mixed Fruit Juice", 1), ("Lay’s Classic Salted Chips", 3), ("Maggi Masala Noodles", 2))),
        PlannedOrder(6, (("Dove Cream Beauty Bathing Bar", 2), ("Clinic Plus Strong & Long Shampoo", 1), ("Harvest Gold White Bread", 1))),
    ),
    6: (),
    7: (
        PlannedOrder(28, (("Shimla Apples", 3), ("Amul Fresh Paneer", 2), ("Amul Taaza Toned Milk", 2))),
        PlannedOrder(8, (("Vim Dishwash Liquid", 1), ("Origami Facial Tissues", 1), ("Farm Fresh Eggs", 2))),
    ),
    8: (PlannedOrder(17, (("Farm Fresh Eggs", 2), ("Fresh Potatoes", 3), ("Farm Fresh Tomatoes", 2), ("Lay’s Classic Salted Chips", 2))),),
    9: (PlannedOrder(10, (("Harvest Gold White Bread", 1), ("Yelakki Bananas", 2), ("Bisleri Mineral Water", 3), ("Cadbury Dairy Milk", 1))),),
}


def _require_existing_sqlite_database(engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        raise ValueError("Demo order history seeding requires the configured SQLite database.")
    database_path = engine.url.database
    if not database_path or database_path == ":memory:":
        raise FileNotFoundError("A persistent existing SQLite database is required; no data was changed.")
    if not Path(database_path).is_file():
        raise FileNotFoundError(
            "The configured SQLite database file does not exist; refusing to create a new database."
        )


def _seed_marker(
    session: Session, customer_id: int, order_id: int, plan_index: int
) -> None:
    session.add(
        CustomerActivity(
            user_id=customer_id,
            event_type=ORDER_MARKER_EVENT_TYPE,
            event_metadata={
                "namespace": ORDER_MARKER_NAMESPACE,
                "order_id": order_id,
                "plan_index": plan_index,
                "source": "scripts.seed_demo_order_histories",
            },
        )
    )


def seed_demo_order_histories(database_engine) -> dict[str, dict[str, int | str]]:
    """Create missing marked orders atomically and return per-customer totals."""
    if not ORDER_PLANS:
        return {}

    created_by_email: dict[str, int] = {}
    customer_id_by_email: dict[str, int] = {}
    customer_ids = {
        number: f"customer{number:02d}@{DEMO_EMAIL_DOMAIN}"
        for number in ORDER_PLANS
    }

    with Session(database_engine) as session, session.begin():
        users = {
            user.email: user
            for user in session.scalars(
                select(User).where(User.email.in_(customer_ids.values()))
            ).all()
        }
        for number, email in customer_ids.items():
            user = users.get(email)
            if user is None or user.role != "customer" or user.name != f"Demo Customer {number:02d}":
                raise RuntimeError(
                    f"Seed-verified customer {email} is missing or unexpected; no orders were created."
                )
            manifest = session.scalar(
                select(CustomerActivity).where(
                    CustomerActivity.user_id == user.id,
                    CustomerActivity.event_type == DEMO_MANIFEST_EVENT_TYPE,
                )
            )
            if (
                manifest is None
                or not isinstance(manifest.event_metadata, dict)
                or manifest.event_metadata.get("namespace") != DEMO_NAMESPACE
            ):
                raise RuntimeError(
                    f"Customer {email} lacks the expected demo seed marker; no orders were created."
                )
            customer_id_by_email[email] = user.id

        expected_names = {
            name for plan_set in ORDER_PLANS.values() for plan in plan_set for name, _ in plan.lines
        }
        products = {
            product.name: product
            for product in session.scalars(select(Product).where(Product.name.in_(expected_names))).all()
        }
        missing_names = expected_names - set(products)
        if missing_names:
            raise RuntimeError(
                "Required existing catalogue products are missing: "
                + ", ".join(sorted(missing_names))
                + ". No orders were created."
            )

        now = utc_now()
        for number, email in customer_ids.items():
            user = users[email]
            markers = session.scalars(
                select(CustomerActivity).where(
                    CustomerActivity.user_id == user.id,
                    CustomerActivity.event_type == ORDER_MARKER_EVENT_TYPE,
                )
            ).all()
            marked_plan_indexes: set[int] = set()
            for marker in markers:
                metadata = marker.event_metadata
                if not isinstance(metadata, dict) or metadata.get("namespace") != ORDER_MARKER_NAMESPACE:
                    raise RuntimeError(
                        f"Unexpected order-history marker for {email}; no orders were created."
                    )
                order_id = metadata.get("order_id")
                plan_index = metadata.get("plan_index")
                if isinstance(order_id, bool) or not isinstance(order_id, int):
                    raise RuntimeError(f"Invalid order-history marker for {email}; no orders were created.")
                if (
                    isinstance(plan_index, bool)
                    or not isinstance(plan_index, int)
                    or not 0 <= plan_index < len(ORDER_PLANS[number])
                    or plan_index in marked_plan_indexes
                ):
                    raise RuntimeError(f"Invalid order plan marker for {email}; no orders were created.")
                order = session.get(Order, order_id)
                if (
                    order is None
                    or order.user_id != user.id
                    or order.status != SIMULATED_COMPLETED_STATUS
                ):
                    raise RuntimeError(f"Order marker does not match an order for {email}; no orders were created.")
                marked_plan_indexes.add(plan_index)

            created = 0
            for plan_index, plan in enumerate(ORDER_PLANS[number]):
                if plan_index in marked_plan_indexes:
                    continue
                cart_lines = [
                    (products[name].id, quantity)
                    for name, quantity in plan.lines
                ]
                existing_latest = session.scalar(
                    select(func.max(Order.created_at)).where(Order.user_id == user.id)
                )
                order = create_simulated_order(
                    session, user.id, cart_lines, commit=False
                )
                planned_created_at = now - timedelta(days=plan.days_ago, seconds=number * 17 + plan_index)
                order.created_at = planned_created_at
                if existing_latest is not None and order.created_at <= existing_latest:
                    raise RuntimeError(
                        f"Planned demo order date is not later than existing history for {email}; no orders were committed."
                    )
                session.flush()
                _seed_marker(session, user.id, order.id, plan_index)
                created += 1
            created_by_email[email] = created
            session.flush()

    result: dict[str, dict[str, int | str]] = {}
    with Session(database_engine) as session:
        for email in customer_ids.values():
            user_id = customer_id_by_email[email]
            completed_count = session.scalar(
                select(func.count(Order.id)).where(
                    Order.user_id == user_id,
                    Order.status == SIMULATED_COMPLETED_STATUS,
                )
            ) or 0
            revenue = session.scalar(
                select(func.sum(Order.total_amount)).where(
                    Order.user_id == user_id,
                    Order.status == SIMULATED_COMPLETED_STATUS,
                )
            ) or Decimal("0.00")
            result[email] = {
                "new_orders": created_by_email[email],
                "completed_orders": int(completed_count),
                "historical_revenue": f"{Decimal(revenue):.2f}",
            }
    return result


def main() -> None:
    engine = create_database_engine()
    try:
        _require_existing_sqlite_database(engine)
        summary = seed_demo_order_histories(engine)
        print("Simulated order history summary (existing completed-order revenue):")
        for email, values in summary.items():
            print(
                f"{email}: new_orders={values['new_orders']}, "
                f"completed_orders={values['completed_orders']}, "
                f"historical_revenue=INR {values['historical_revenue']}"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
