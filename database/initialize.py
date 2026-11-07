"""Explicit database table creation and approved-offer seeding."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, joinedload

from .base import Base
from .config import engine as default_engine
from . import models as _models  # Register model tables with Base.metadata.
from .models import Offer, RetentionIntervention, RetentionOfferValidity
from services.commerce_config import DEFAULT_OFFER_VALIDITY_DAYS


APPROVED_OFFERS = (
    {
        "code": "NO_OFFER",
        "name": "No offer",
        "description": "No incentive",
        "discount_percentage": None,
        "maximum_cost": Decimal("0.00"),
    },
    {
        "code": "SMALL_DISCOUNT",
        "name": "Small discount",
        "description": "5% discount, capped at ₹100",
        "discount_percentage": Decimal("5.00"),
        "maximum_cost": Decimal("100.00"),
    },
    {
        "code": "LARGE_DISCOUNT",
        "name": "Large discount",
        "description": "10% discount, capped at ₹250",
        "discount_percentage": Decimal("10.00"),
        "maximum_cost": Decimal("250.00"),
    },
    {
        "code": "FREE_SHIPPING",
        "name": "Free shipping",
        "description": "Waive shipping fee",
        "discount_percentage": None,
        "maximum_cost": Decimal("60.00"),
    },
)


def initialize_database(
    database_engine: Engine | None = None,
    *,
    offer_validity_days: int = DEFAULT_OFFER_VALIDITY_DAYS,
) -> None:
    """Create missing tables and insert approved offers that are not present.

    Existing tables and offer rows are preserved. This function is safe to run
    more than once and never drops or recreates the database.
    """

    target_engine = database_engine or default_engine
    Base.metadata.create_all(target_engine)

    with Session(target_engine) as session:
        existing_codes = set(session.scalars(select(Offer.code)).all())
        for offer_data in APPROVED_OFFERS:
            if offer_data["code"] not in existing_codes:
                session.add(Offer(**offer_data))
        session.commit()

        # One-time, additive backfill for active offers already in a database.
        # The expiry is anchored to the original assignment timestamp and is
        # never recomputed on later application starts.
        interventions = session.scalars(
            select(RetentionIntervention)
            .options(
                joinedload(RetentionIntervention.offer),
                joinedload(RetentionIntervention.validity),
            )
            .where(~RetentionIntervention.validity.has())
        ).all()
        for intervention in interventions:
            if intervention.offer.code == "NO_OFFER" or intervention.validity is not None:
                continue
            session.add(
                RetentionOfferValidity(
                    intervention_id=intervention.id,
                    expires_at=intervention.created_at
                    + timedelta(days=offer_validity_days),
                )
            )
        session.commit()


if __name__ == "__main__":
    initialize_database()
    print("Database tables are ready and approved offers are seeded.")

