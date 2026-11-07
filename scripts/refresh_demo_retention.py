"""Refresh selected demo customers from the local command line.

This explicit local operation calls the existing retention service directly.
It is not exposed as an unauthenticated API route. Run it from the repository
root and supply both customer IDs and the total retention budget.
"""

from __future__ import annotations

import argparse
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.models import CustomerActivity, User
from scripts.seed_demo_data import (
    DEMO_EMAIL_DOMAIN,
    DEMO_MANIFEST_EVENT_TYPE,
    DEMO_NAMESPACE,
)
from services.churn_inference import ChurnInferenceService
from services.customer_retention import RetentionRefreshResult, refresh_customer_retention


def positive_customer_id(value: str) -> int:
    """Parse a positive integer customer ID for the explicit CLI selection."""
    try:
        customer_id = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("customer IDs must be positive integers") from exc
    if customer_id <= 0:
        raise argparse.ArgumentTypeError("customer IDs must be positive integers")
    return customer_id


def nonnegative_budget(value: str) -> float:
    """Parse a finite, nonnegative retention budget in rupees."""
    try:
        budget = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("budget must be a nonnegative number") from exc
    if not math.isfinite(budget) or budget < 0:
        raise argparse.ArgumentTypeError("budget must be a finite, nonnegative number")
    return budget


def refresh_demo_customers(
    session: Session,
    inference_service: ChurnInferenceService,
    customer_ids: list[int],
    total_budget: float,
) -> RetentionRefreshResult:
    """Validate seed-marked demo IDs, then delegate to the persisted workflow."""
    if not customer_ids:
        raise ValueError("Select at least one demo customer ID.")
    if len(customer_ids) != len(set(customer_ids)):
        raise ValueError("Demo customer IDs must not contain duplicates.")

    users = session.scalars(select(User).where(User.id.in_(customer_ids))).all()
    users_by_id = {user.id: user for user in users}
    for customer_id in customer_ids:
        user = users_by_id.get(customer_id)
        if (
            user is None
            or user.role != "customer"
            or not user.email.endswith(f"@{DEMO_EMAIL_DOMAIN}")
        ):
            raise ValueError("Selected IDs must identify seed-marked demo customers.")
        manifest = session.scalar(
            select(CustomerActivity).where(
                CustomerActivity.user_id == customer_id,
                CustomerActivity.event_type == DEMO_MANIFEST_EVENT_TYPE,
            )
        )
        if (
            manifest is None
            or not isinstance(manifest.event_metadata, dict)
            or manifest.event_metadata.get("namespace") != DEMO_NAMESPACE
        ):
            raise ValueError("Selected IDs must identify seed-marked demo customers.")

    return refresh_customer_retention(
        session=session,
        inference_service=inference_service,
        customer_ids=customer_ids,
        total_budget=total_budget,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--customer-ids",
        type=positive_customer_id,
        nargs="+",
        required=True,
        help="explicit customer IDs to refresh",
    )
    parser.add_argument(
        "--total-budget",
        type=nonnegative_budget,
        required=True,
        help="explicit total retention budget in rupees",
    )
    parser.add_argument(
        "--confirm-local-demo-refresh",
        action="store_true",
        required=True,
        help="acknowledge that selected customers' retention state will be persisted",
    )
    args = parser.parse_args()

    engine = create_database_engine()
    try:
        inference_service = ChurnInferenceService()
        with Session(engine) as session:
            result = refresh_demo_customers(
                session,
                inference_service,
                args.customer_ids,
                args.total_budget,
            )
    except Exception as exc:
        parser.exit(1, f"Demo retention refresh failed: {exc}\n")
    finally:
        engine.dispose()

    print(f"Persisted {len(result.predictions)} churn predictions.")
    # ASCII currency labels work in the default Windows console encoding too.
    print(f"Initial budget: INR {result.decisions.summary.initial_budget:.2f}")
    print(f"Allocated: INR {result.decisions.summary.total_estimated_budget_allocated:.2f}")
    print(f"Remaining: INR {result.decisions.summary.remaining_budget:.2f}")
    for decision in result.decisions.customers:
        print(
            f"Customer {decision.customer_id}: "
            f"{decision.selected_intervention} "
            f"(estimated cost INR {decision.estimated_intervention_cost:.2f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
