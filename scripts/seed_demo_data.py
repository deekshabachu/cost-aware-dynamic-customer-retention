"""Manually seed repeatable, local-only demo customers and order histories.

Run from the project directory with ``python -m scripts.seed_demo_data``.
The script initializes missing database tables/offers, but never drops or
resets the database and never runs as part of application startup.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import secrets
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.base import utc_now
from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import CustomerActivity, Order, User
from services.customer_retention import MODEL_FEATURES_EVENT_TYPE


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPROCESSOR_PATH = PROJECT_ROOT / "models" / "preprocessor.pkl"
DEMO_NAMESPACE = "customer-retention-demo-v1"
DEMO_EMAIL_DOMAIN = "demo.customer-retention.local"
DEMO_MANIFEST_EVENT_TYPE = "demo_seed_manifest"

_NUMERICAL_PROFILES: tuple[dict[str, int | float], ...] = (
    {
        "Tenure": 8,
        "CityTier": 1,
        "WarehouseToHome": 6,
        "HourSpendOnApp": 3,
        "NumberOfDeviceRegistered": 3,
        "SatisfactionScore": 4,
        "NumberOfAddress": 2,
        "Complain": 0,
        "OrderAmountHikeFromlastYear": 15,
        "CouponUsed": 2,
        "OrderCount": 3,
        "DaySinceLastOrder": 4,
        "CashbackAmount": 120.5,
    },
    {
        "Tenure": 1,
        "CityTier": 2,
        "WarehouseToHome": 18,
        "HourSpendOnApp": 1,
        "NumberOfDeviceRegistered": 2,
        "SatisfactionScore": 2,
        "NumberOfAddress": 3,
        "Complain": 1,
        "OrderAmountHikeFromlastYear": 12,
        "CouponUsed": 0,
        "OrderCount": 1,
        "DaySinceLastOrder": 28,
        "CashbackAmount": 75.0,
    },
    {
        "Tenure": 32,
        "CityTier": 1,
        "WarehouseToHome": 10,
        "HourSpendOnApp": 4,
        "NumberOfDeviceRegistered": 5,
        "SatisfactionScore": 5,
        "NumberOfAddress": 4,
        "Complain": 0,
        "OrderAmountHikeFromlastYear": 22,
        "CouponUsed": 5,
        "OrderCount": 8,
        "DaySinceLastOrder": 2,
        "CashbackAmount": 280.0,
    },
    {
        "Tenure": 5,
        "CityTier": 3,
        "WarehouseToHome": 30,
        "HourSpendOnApp": 2,
        "NumberOfDeviceRegistered": 3,
        "SatisfactionScore": 3,
        "NumberOfAddress": 1,
        "Complain": 1,
        "OrderAmountHikeFromlastYear": 13,
        "CouponUsed": 1,
        "OrderCount": 2,
        "DaySinceLastOrder": 16,
        "CashbackAmount": 110.0,
    },
    {
        "Tenure": 18,
        "CityTier": 2,
        "WarehouseToHome": 14,
        "HourSpendOnApp": 5,
        "NumberOfDeviceRegistered": 4,
        "SatisfactionScore": 4,
        "NumberOfAddress": 5,
        "Complain": 0,
        "OrderAmountHikeFromlastYear": 19,
        "CouponUsed": 3,
        "OrderCount": 6,
        "DaySinceLastOrder": 3,
        "CashbackAmount": 210.0,
    },
    {
        "Tenure": 0,
        "CityTier": 1,
        "WarehouseToHome": 8,
        "HourSpendOnApp": 1,
        "NumberOfDeviceRegistered": 1,
        "SatisfactionScore": 1,
        "NumberOfAddress": 1,
        "Complain": 1,
        "OrderAmountHikeFromlastYear": 11,
        "CouponUsed": 0,
        "OrderCount": 1,
        "DaySinceLastOrder": 46,
        "CashbackAmount": 0.0,
    },
    {
        "Tenure": 45,
        "CityTier": 3,
        "WarehouseToHome": 22,
        "HourSpendOnApp": 4,
        "NumberOfDeviceRegistered": 6,
        "SatisfactionScore": 5,
        "NumberOfAddress": 7,
        "Complain": 0,
        "OrderAmountHikeFromlastYear": 26,
        "CouponUsed": 8,
        "OrderCount": 12,
        "DaySinceLastOrder": 1,
        "CashbackAmount": 324.99,
    },
    {
        "Tenure": 12,
        "CityTier": 2,
        "WarehouseToHome": 5,
        "HourSpendOnApp": 3,
        "NumberOfDeviceRegistered": 4,
        "SatisfactionScore": 3,
        "NumberOfAddress": 2,
        "Complain": 0,
        "OrderAmountHikeFromlastYear": 17,
        "CouponUsed": 2,
        "OrderCount": 4,
        "DaySinceLastOrder": 7,
        "CashbackAmount": 155.25,
    },
    {
        "Tenure": 3,
        "CityTier": 1,
        "WarehouseToHome": 12,
        "HourSpendOnApp": 2,
        "NumberOfDeviceRegistered": 2,
        "SatisfactionScore": 2,
        "NumberOfAddress": 3,
        "Complain": 1,
        "OrderAmountHikeFromlastYear": 14,
        "CouponUsed": 1,
        "OrderCount": 2,
        "DaySinceLastOrder": 21,
        "CashbackAmount": 90.0,
    },
)

# Order totals are kept as strings so Decimal receives exact currency values.
DEMO_CUSTOMERS: tuple[dict[str, Any], ...] = (
    {
        "name": "Demo Customer 01",
        "orders": [("1299.00", "completed"), ("499.00", "completed")],
    },
    {"name": "Demo Customer 02", "orders": [("1200.00", "pending")]},
    {
        "name": "Demo Customer 03",
        "orders": [("2500.00", "completed"), ("1450.00", "completed")],
    },
    {"name": "Demo Customer 04", "orders": [("249.99", "completed")]},
    {
        "name": "Demo Customer 05",
        "orders": [
            ("300.00", "completed"),
            ("450.00", "completed"),
            ("125.00", "completed"),
        ],
    },
    {"name": "Demo Customer 06", "orders": []},
    {"name": "Demo Customer 07", "orders": [("4999.00", "completed")]},
    {
        "name": "Demo Customer 08",
        "orders": [("189.99", "completed"), ("250.00", "completed")],
    },
    {
        "name": "Demo Customer 09",
        "orders": [("75.00", "completed"), ("89.00", "completed")],
    },
)


def _load_feature_schema(
    preprocessor_path: str | Path = PREPROCESSOR_PATH,
) -> tuple[list[str], dict[str, list[Any]]]:
    """Return raw names and fitted encoder categories from the saved pipeline."""
    path = Path(preprocessor_path)
    if not path.is_file():
        raise FileNotFoundError(f"Saved preprocessor was not found: {path}")
    preprocessor = joblib.load(path)
    feature_names = [str(name) for name in preprocessor.feature_names_in_]
    categorical_names = list(preprocessor.transformers_[1][2])
    encoder = preprocessor.named_transformers_["categorical"].named_steps["encoder"]
    categories = {
        str(name): [value.item() if hasattr(value, "item") else value for value in values]
        for name, values in zip(categorical_names, encoder.categories_)
    }
    if len(categories) != len(categorical_names) or any(not values for values in categories.values()):
        raise ValueError("The saved preprocessor does not expose fitted categories.")
    return feature_names, categories


def _feature_snapshot(
    customer_index: int,
    feature_names: list[str],
    categories: dict[str, list[Any]],
) -> dict[str, Any]:
    """Build a raw feature row using numeric values and fitted categories."""
    numeric_values = _NUMERICAL_PROFILES[customer_index]
    numerical_names = set(feature_names) - set(categories)
    if set(numeric_values) != numerical_names:
        raise ValueError(
            "Demo numerical profile fields do not match the saved preprocessor."
        )
    snapshot: dict[str, Any] = {}
    for feature_position, name in enumerate(feature_names):
        if name in numeric_values:
            snapshot[name] = numeric_values[name]
        elif name in categories:
            values = categories[name]
            snapshot[name] = values[(customer_index + feature_position) % len(values)]
        else:
            raise ValueError(f"No demo value is defined for model feature {name!r}.")

    if set(snapshot) != set(feature_names):
        raise ValueError("Generated demo features do not match the preprocessor schema.")
    return snapshot


def _hash_demo_password(password: str) -> str:
    """Hash the local demo password with scrypt and a unique random salt."""
    if not password:
        raise ValueError("A non-empty password is required for hashing.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def seed_demo_data(
    database_engine=None,
    *,
    preprocessor_path: str | Path = PREPROCESSOR_PATH,
) -> list[tuple[int, str]]:
    """Seed or reuse the nine namespaced demo customers without resetting data."""
    engine = database_engine or create_database_engine()
    if len(_NUMERICAL_PROFILES) != len(DEMO_CUSTOMERS):
        raise ValueError("Each demo customer must have one numerical feature profile.")
    initialize_database(engine)
    created_or_reused: list[tuple[int, str]] = []
    feature_names, categories = _load_feature_schema(preprocessor_path)
    snapshots = [
        _feature_snapshot(index, feature_names, categories)
        for index in range(len(DEMO_CUSTOMERS))
    ]

    with Session(engine) as session, session.begin():
        for index, demo in enumerate(DEMO_CUSTOMERS):
            customer_number = index + 1
            email = f"customer{customer_number:02d}@{DEMO_EMAIL_DOMAIN}"
            user = session.scalar(select(User).where(User.email == email))

            if user is not None:
                manifest = session.scalar(
                    select(CustomerActivity).where(
                        CustomerActivity.user_id == user.id,
                        CustomerActivity.event_type == DEMO_MANIFEST_EVENT_TYPE,
                    )
                )
                if (
                    user.name != demo["name"]
                    or user.role != "customer"
                    or manifest is None
                    or not isinstance(manifest.event_metadata, dict)
                    or manifest.event_metadata.get("namespace") != DEMO_NAMESPACE
                ):
                    raise RuntimeError(
                        f"Reserved demo email {email} already exists without this "
                        "script's seed marker; no records were changed."
                    )
                created_or_reused.append((user.id, email))
                continue

            user = User(
                name=demo["name"],
                email=email,
                # Give each new account a distinct, undisclosed initial secret.
                # The local credential setup script can set a known password
                # for selected seed-verified demo accounts afterward.
                password_hash=_hash_demo_password(secrets.token_urlsafe(32)),
                role="customer",
            )
            session.add(user)
            session.flush()

            snapshot = CustomerActivity(
                user_id=user.id,
                event_type=MODEL_FEATURES_EVENT_TYPE,
                event_metadata=snapshots[index],
            )
            session.add(snapshot)
            seeded_orders: list[Order] = []
            for order_index, (amount, status) in enumerate(demo["orders"]):
                order = Order(
                    user_id=user.id,
                    total_amount=Decimal(amount),
                    status=status,
                    created_at=utc_now() - timedelta(days=30 + order_index * 17 + index),
                )
                seeded_orders.append(order)
                session.add(order)

            session.flush()
            session.add(
                CustomerActivity(
                    user_id=user.id,
                    event_type=DEMO_MANIFEST_EVENT_TYPE,
                    event_metadata={
                        "namespace": DEMO_NAMESPACE,
                        "snapshot_activity_id": snapshot.id,
                        "order_ids": [order.id for order in seeded_orders],
                    },
                )
            )
            created_or_reused.append((user.id, email))

    return created_or_reused


def main() -> None:
    """Run the explicit seed operation against the configured database URL."""
    engine = create_database_engine()
    try:
        customers = seed_demo_data(engine)
        print("Demo customers created or reused:")
        for customer_id, email in customers:
            print(f"  id={customer_id} email={email}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

