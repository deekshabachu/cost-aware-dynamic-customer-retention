"""Read-only checks for the nine seed-verified LittleLeaf demo customers.

Run manually with ``python -m scripts.verify_demo_customers``. This validates
database identities, customer roles, feature snapshots against the saved
inference artifacts, and current account-facing offer state. It never changes
passwords, orders, snapshots, predictions, or interventions. It does not test a
password login because passwords are neither read nor requested here.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.models import CustomerActivity, Order, RetentionIntervention, User
from scripts.seed_demo_data import DEMO_EMAIL_DOMAIN, DEMO_MANIFEST_EVENT_TYPE, DEMO_NAMESPACE
from services.churn_inference import ChurnInferenceService
from services.customer_retention import MODEL_FEATURES_EVENT_TYPE


def _require_existing_sqlite_database(engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        raise ValueError("Demo account verification requires the configured SQLite database.")
    database_path = engine.url.database
    if not database_path or database_path == ":memory:" or not Path(database_path).is_file():
        raise FileNotFoundError("The existing SQLite database file was not found; verification did not create one.")


def verify_demo_customers(database_engine) -> list[dict[str, int | str]]:
    """Verify all nine expected customer identities and usable feature snapshots."""
    inference = ChurnInferenceService()
    expected = {
        f"customer{number:02d}@{DEMO_EMAIL_DOMAIN}": number
        for number in range(1, 10)
    }
    rows: list[dict[str, int | str]] = []
    with Session(database_engine) as session:
        users = {
            user.email: user
            for user in session.scalars(select(User).where(User.email.in_(expected))).all()
        }
        missing = set(expected) - set(users)
        if missing:
            raise RuntimeError("Missing demo customer accounts: " + ", ".join(sorted(missing)))

        user_ids: list[int] = []
        snapshots: list[dict[str, object]] = []
        snapshots_by_email: dict[str, tuple[int, int, dict[str, object]]] = {}
        for email, number in expected.items():
            user = users[email]
            if user.role != "customer" or user.name != f"Demo Customer {number:02d}":
                raise RuntimeError(f"Demo identity or customer role did not match for {email}.")
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
                raise RuntimeError(f"The expected demo marker is missing for {email}.")
            feature_rows = session.scalars(
                select(CustomerActivity)
                .where(
                    CustomerActivity.user_id == user.id,
                    CustomerActivity.event_type == MODEL_FEATURES_EVENT_TYPE,
                )
                .order_by(CustomerActivity.created_at.desc(), CustomerActivity.id.desc())
            ).all()
            if not feature_rows or not isinstance(feature_rows[0].event_metadata, dict):
                raise RuntimeError(f"A model feature snapshot is missing for {email}.")
            user_ids.append(user.id)
            snapshots.append(feature_rows[0].event_metadata)
            snapshots_by_email[email] = (user.id, len(feature_rows), feature_rows[0].event_metadata)

        # This runs the saved, read-only inference path to verify every stored
        # snapshot has the exact feature schema and accepted fitted categories.
        predictions = inference.predict_batch(user_ids, snapshots)
        if len(predictions) != len(expected):
            raise RuntimeError("Not all feature snapshots passed model inference validation.")

        for email, number in expected.items():
            user_id, feature_count, _ = snapshots_by_email[email]
            order_count = session.scalar(
                select(func.count(Order.id)).where(Order.user_id == user_id)
            ) or 0
            completed_count = session.scalar(
                select(func.count(Order.id)).where(
                    Order.user_id == user_id, Order.status == "completed"
                )
            ) or 0
            revenue = session.scalar(
                select(func.sum(Order.total_amount)).where(
                    Order.user_id == user_id, Order.status == "completed"
                )
            ) or 0
            latest_intervention = session.scalar(
                select(RetentionIntervention)
                .where(RetentionIntervention.user_id == user_id)
                .order_by(RetentionIntervention.created_at.desc(), RetentionIntervention.id.desc())
                .limit(1)
            )
            if latest_intervention is None:
                offer_state = "no saved intervention"
            elif latest_intervention.status == "active":
                offer_state = f"active {latest_intervention.offer.code}"
            else:
                offer_state = f"no active offer (latest status {latest_intervention.status})"
            rows.append(
                {
                    "email": email,
                    "customer_id": user_id,
                    "role": user.role,
                    "feature_snapshots": feature_count,
                    "customer_orders": int(order_count),
                    "completed_orders": int(completed_count),
                    "historical_revenue": f"{revenue:.2f}",
                    "offer_state": offer_state,
                }
            )
    return rows


def main() -> None:
    engine = create_database_engine()
    try:
        _require_existing_sqlite_database(engine)
        rows = verify_demo_customers(engine)
        print("Read-only demo account and feature-snapshot verification:")
        for row in rows:
            print(
                f"{row['email']} id={row['customer_id']} role={row['role']} "
                f"snapshots={row['feature_snapshots']} model_schema=valid "
                f"orders={row['customer_orders']} completed={row['completed_orders']} "
                f"revenue=INR {row['historical_revenue']} offer={row['offer_state']}"
            )
        print("Note: password logins are not attempted; credentials are not read or requested.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
