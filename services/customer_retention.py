"""Database-backed prediction and retention decision workflow.

Raw model features are stored on ``CustomerActivity`` rows with
``event_type="model_features_snapshot"``. The row's ``event_metadata`` must
be a flat JSON object containing exactly the preprocessor's raw feature names;
``CustomerID`` and ``Churn`` are not included. The latest snapshot by
``created_at`` (then row ID) is used for each customer.

On refresh, any prior ``active`` intervention is marked ``superseded``. The
new decision is recorded as ``active`` when it assigns a paid offer and as
``no_offer`` otherwise. Predictions, superseding, and new intervention rows
are committed together. Repeated refreshes therefore retain history without
leaving more than one active intervention per customer in normal sequential
use.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from database.models import (
    CustomerActivity,
    Offer,
    Order,
    RetentionIntervention,
    RetentionOfferValidity,
    RetentionPrediction,
    User,
)
from retention import CustomerInput, DecisionResult, decide_retention
from retention.interventions import INTERVENTION_CATALOGUE
from services.churn_inference import ChurnInferenceService, ChurnPrediction
from services.commerce_config import DEFAULT_OFFER_VALIDITY_DAYS
from database.base import utc_now


MODEL_FEATURES_EVENT_TYPE = "model_features_snapshot"
ACTIVE_INTERVENTION_STATUS = "active"
SUPERSEDED_INTERVENTION_STATUS = "superseded"
NO_OFFER_INTERVENTION_STATUS = "no_offer"


class UnknownCustomerError(ValueError):
    """Raised when an ID is missing or does not identify a customer account."""


class MissingCustomerFeaturesError(ValueError):
    """Raised when a customer has no usable stored feature snapshot."""


class ExistingActiveInterventionError(ValueError):
    """Raised when a customer already has a paid active assignment."""


@dataclass(frozen=True)
class RetentionRefreshResult:
    """Predictions and policy decisions produced by one persisted refresh."""

    predictions: list[ChurnPrediction]
    decisions: DecisionResult


@dataclass(frozen=True)
class CustomerEvaluationResult:
    """One persisted, selected-customer evaluation using the shared budget."""

    prediction: ChurnPrediction
    decision: DecisionResult
    budget_available: float
    customer_email: str


@dataclass(frozen=True)
class BulkCustomerOutcome:
    """One account's result in a bulk run, including missing/protected states."""

    customer_id: int
    customer_email: str
    has_feature_snapshot: bool
    churn_probability: float | None
    historical_revenue: float | None
    priority_score: float | None
    eligible: bool | None
    intervention_code: str | None
    estimated_intervention_cost: float | None
    preserved_existing_offer: bool
    preserved_redeemed_offer: bool
    new_offer_generated: bool
    status: str


@dataclass(frozen=True)
class BulkRetentionEvaluationResult:
    """Persistent summary data produced by one bulk evaluation transaction."""

    customer_outcomes: list[BulkCustomerOutcome]
    total_accounts: int
    customers_evaluated: int
    customers_missing_feature_snapshot: int
    customers_below_threshold: int
    customers_eligible: int
    customers_receiving_no_offer: int
    existing_offers_preserved: int
    existing_redeemed_offers_preserved: int
    new_offers_generated: int
    total_new_offer_cost: float
    total_committed_reserved_cost: float
    remaining_budget: float
    intervention_counts: dict[str, int]
    threshold: float
    initial_budget: float
    created_at: datetime


def evaluate_all_customer_retention(
    session: Session,
    inference_service: ChurnInferenceService,
    total_budget: float,
    eligibility_threshold: float,
    *,
    commit: bool = True,
    offer_validity_days: int = DEFAULT_OFFER_VALIDITY_DAYS,
) -> BulkRetentionEvaluationResult:
    """Evaluate every customer snapshot and safely allocate one shared budget.

    Redeemed paid interventions and active, unexpired paid offers are protected:
    their records are never superseded, their customers receive no duplicate
    assignment, and their cost is reserved against the configured budget.
    Predictions are still refreshed for every customer with a valid snapshot.
    The caller owns the transaction boundary so the predictions, new decisions,
    and saved run summary can be committed atomically.
    """
    if isinstance(offer_validity_days, bool) or not 1 <= offer_validity_days <= 365:
        raise ValueError("offer_validity_days must be between 1 and 365 days.")
    # Keep policy validation and threshold semantics in the decision engine.
    empty_decision = decide_retention(
        [], total_budget, eligibility_threshold=eligibility_threshold
    )
    initial_budget = Decimal(str(empty_decision.summary.initial_budget))
    now = utc_now()

    customers = session.scalars(
        select(User).where(User.role == "customer").order_by(User.id)
    ).all()
    customer_ids = [customer.id for customer in customers]
    users_by_id = {customer.id: customer for customer in customers}

    snapshot_rows = session.scalars(
        select(CustomerActivity)
        .where(
            CustomerActivity.user_id.in_(customer_ids or [-1]),
            CustomerActivity.event_type == MODEL_FEATURES_EVENT_TYPE,
        )
        .order_by(CustomerActivity.created_at.desc(), CustomerActivity.id.desc())
    ).all()
    latest_snapshots: dict[int, CustomerActivity] = {}
    for row in snapshot_rows:
        latest_snapshots.setdefault(row.user_id, row)
    required_feature_names = set(inference_service.feature_names)
    snapshot_ids = [
        customer_id
        for customer_id in customer_ids
        if customer_id in latest_snapshots
        and isinstance(latest_snapshots[customer_id].event_metadata, dict)
        and set(latest_snapshots[customer_id].event_metadata) == required_feature_names
    ]

    revenue_rows = session.execute(
        select(Order.user_id, func.sum(Order.total_amount))
        .where(
            Order.user_id.in_(snapshot_ids or [-1]),
            Order.status == "completed",
        )
        .group_by(Order.user_id)
    ).all()
    revenue_by_id = {
        user_id: (total or Decimal("0.00")) for user_id, total in revenue_rows
    }
    for customer_id in snapshot_ids:
        revenue_by_id.setdefault(customer_id, Decimal("0.00"))

    predictions = inference_service.predict_batch(
        snapshot_ids,
        [latest_snapshots[customer_id].event_metadata for customer_id in snapshot_ids],
    )
    if len(predictions) != len(snapshot_ids):
        raise RuntimeError("Inference returned a different number of results than customers.")
    prediction_by_id = {prediction.customer_id: prediction for prediction in predictions}
    if set(prediction_by_id) != set(snapshot_ids):
        raise RuntimeError("Inference results did not match the requested customer IDs.")

    interventions = session.scalars(
        select(RetentionIntervention)
        .join(Offer, Offer.id == RetentionIntervention.offer_id)
        .options(
            joinedload(RetentionIntervention.offer),
            joinedload(RetentionIntervention.validity),
            joinedload(RetentionIntervention.redemption),
        )
        .where(RetentionIntervention.user_id.in_(customer_ids or [-1]))
        .order_by(RetentionIntervention.created_at.desc(), RetentionIntervention.id.desc())
    ).unique().all()
    protected_by_customer: dict[int, RetentionIntervention] = {}
    reserved_interventions: dict[int, RetentionIntervention] = {}
    redeemed_customer_ids: set[int] = set()
    for intervention in interventions:
        if intervention.offer.code == "NO_OFFER":
            continue
        redeemed = intervention.redemption is not None
        active_unexpired = (
            intervention.status == ACTIVE_INTERVENTION_STATUS
            and (
                intervention.validity is None
                or intervention.validity.expires_at > now
            )
        )
        if redeemed or active_unexpired:
            reserved_interventions[intervention.id] = intervention
            protected_by_customer.setdefault(intervention.user_id, intervention)
            if redeemed:
                redeemed_customer_ids.add(intervention.user_id)

    reserved_cost = sum(
        (row.intervention_cost for row in reserved_interventions.values()),
        Decimal("0.00"),
    )
    available_budget = max(Decimal("0.00"), initial_budget - reserved_cost)
    allocatable_ids = [
        customer_id
        for customer_id in snapshot_ids
        if customer_id not in protected_by_customer
    ]
    allocatable_decisions = decide_retention(
        [
            CustomerInput(
                customer_id=customer_id,
                churn_probability=prediction_by_id[customer_id].churn_probability,
                historical_revenue=float(revenue_by_id[customer_id]),
            )
            for customer_id in allocatable_ids
        ],
        float(available_budget),
        eligibility_threshold=eligibility_threshold,
    )
    decision_by_id = {
        decision.customer_id: decision
        for decision in allocatable_decisions.customers
    }

    offer_codes = {
        decision.selected_intervention
        for decision in allocatable_decisions.customers
    }
    offers = session.scalars(select(Offer).where(Offer.code.in_(offer_codes))).all()
    offers_by_code = {offer.code: offer for offer in offers}
    missing_codes = offer_codes - set(offers_by_code)
    if missing_codes:
        raise RuntimeError(f"Approved offers are missing from the database: {sorted(missing_codes)}")

    # Persist every fresh prediction. Protected existing intervention records
    # remain untouched; expired current assignments may be superseded only when
    # the customer is being evaluated for a replacement decision.
    for customer_id in snapshot_ids:
        prediction = prediction_by_id[customer_id]
        session.add(
            RetentionPrediction(
                user_id=customer_id,
                churn_probability=Decimal(str(prediction.churn_probability)),
                customer_value=revenue_by_id[customer_id],
                model_version=prediction.model_version,
            )
        )

    existing_current = session.scalars(
        select(RetentionIntervention).where(
            RetentionIntervention.user_id.in_(allocatable_ids or [-1]),
            RetentionIntervention.status == ACTIVE_INTERVENTION_STATUS,
        )
    ).all()
    for intervention in existing_current:
        intervention.status = SUPERSEDED_INTERVENTION_STATUS

    created_at = utc_now()
    newly_assigned_cost = Decimal("0.00")
    for decision in allocatable_decisions.customers:
        offer = offers_by_code[decision.selected_intervention]
        intervention = RetentionIntervention(
            user_id=int(decision.customer_id),
            offer_id=offer.id,
            intervention_cost=Decimal(str(decision.estimated_intervention_cost)),
            priority_score=Decimal(str(decision.priority_score)),
            decision_reason=decision.decision_explanation,
            status=(
                ACTIVE_INTERVENTION_STATUS
                if decision.selected_intervention != "NO_OFFER"
                else NO_OFFER_INTERVENTION_STATUS
            ),
            created_at=created_at,
        )
        session.add(intervention)
        if decision.selected_intervention != "NO_OFFER":
            newly_assigned_cost += Decimal(str(decision.estimated_intervention_cost))
            session.add(
                RetentionOfferValidity(
                    intervention=intervention,
                    expires_at=created_at + timedelta(days=offer_validity_days),
                )
            )

    outcomes: list[BulkCustomerOutcome] = []
    intervention_counts = {code: 0 for code in INTERVENTION_CATALOGUE}
    below_threshold = 0
    eligible_count = 0
    no_offer_count = 0
    for customer_id in customer_ids:
        customer = users_by_id[customer_id]
        if customer_id not in latest_snapshots or customer_id not in prediction_by_id:
            outcomes.append(
                BulkCustomerOutcome(
                    customer_id=customer_id,
                    customer_email=customer.email,
                    has_feature_snapshot=False,
                    churn_probability=None,
                    historical_revenue=None,
                    priority_score=None,
                    eligible=None,
                    intervention_code=None,
                    estimated_intervention_cost=None,
                    preserved_existing_offer=False,
                    preserved_redeemed_offer=False,
                    new_offer_generated=False,
                    status="missing_feature_data",
                )
            )
            continue

        prediction = prediction_by_id[customer_id]
        churn = prediction.churn_probability
        revenue = float(revenue_by_id[customer_id])
        eligible = churn >= float(eligibility_threshold)
        if eligible:
            eligible_count += 1
        else:
            below_threshold += 1

        protected = protected_by_customer.get(customer_id)
        decision = decision_by_id.get(customer_id)
        if protected is not None:
            code = protected.offer.code
            cost = float(protected.intervention_cost)
            priority = float(protected.priority_score)
            preserved = True
            redeemed = customer_id in redeemed_customer_ids
            generated = False
            outcome_status = "preserved_redeemed" if redeemed else "preserved_active"
        else:
            assert decision is not None
            code = decision.selected_intervention
            cost = decision.estimated_intervention_cost
            priority = decision.priority_score
            preserved = False
            redeemed = False
            generated = code != "NO_OFFER"
            outcome_status = "assigned" if generated else "no_offer"

        intervention_counts[code] = intervention_counts.get(code, 0) + 1
        if code == "NO_OFFER":
            no_offer_count += 1
        outcomes.append(
            BulkCustomerOutcome(
                customer_id=customer_id,
                customer_email=customer.email,
                has_feature_snapshot=True,
                churn_probability=churn,
                historical_revenue=revenue,
                priority_score=priority,
                eligible=eligible,
                intervention_code=code,
                estimated_intervention_cost=cost,
                preserved_existing_offer=preserved,
                preserved_redeemed_offer=redeemed,
                new_offer_generated=generated,
                status=outcome_status,
            )
        )

    committed_reserved = reserved_cost + newly_assigned_cost
    remaining_budget = max(Decimal("0.00"), initial_budget - committed_reserved)
    if commit:
        session.commit()

    return BulkRetentionEvaluationResult(
        customer_outcomes=outcomes,
        total_accounts=len(customers),
        customers_evaluated=len(snapshot_ids),
        customers_missing_feature_snapshot=len(customers) - len(snapshot_ids),
        customers_below_threshold=below_threshold,
        customers_eligible=eligible_count,
        customers_receiving_no_offer=no_offer_count,
        existing_offers_preserved=len(reserved_interventions),
        existing_redeemed_offers_preserved=sum(
            1 for row in reserved_interventions.values() if row.redemption is not None
        ),
        new_offers_generated=sum(
            1 for outcome in outcomes if outcome.new_offer_generated
        ),
        total_new_offer_cost=float(newly_assigned_cost),
        total_committed_reserved_cost=float(committed_reserved),
        remaining_budget=float(remaining_budget),
        intervention_counts=intervention_counts,
        threshold=float(eligibility_threshold),
        initial_budget=float(initial_budget),
        created_at=created_at,
    )


def refresh_customer_retention(
    session: Session,
    inference_service: ChurnInferenceService,
    customer_ids: Sequence[int],
    total_budget: float,
    *,
    commit: bool = True,
    offer_validity_days: int = DEFAULT_OFFER_VALIDITY_DAYS,
) -> RetentionRefreshResult:
    """Recompute and persist predictions and interventions for customer IDs.

    Revenue is the sum of ``total_amount`` for completed orders only. The
    budget is a required call argument and is passed unchanged to the existing
    decision engine, which remains the sole owner of retention policy.
    """
    requested_ids = list(customer_ids)
    if not requested_ids:
        raise ValueError("customer_ids must contain at least one customer ID.")
    if len(requested_ids) != len(set(requested_ids)):
        raise ValueError("customer_ids must not contain duplicates.")
    if isinstance(offer_validity_days, bool) or not 1 <= offer_validity_days <= 365:
        raise ValueError("offer_validity_days must be between 1 and 365 days.")

    # Reuse the decision engine's validation before spending time on inference.
    decide_retention([], total_budget)

    users = session.scalars(
        select(User).where(User.id.in_(requested_ids))
    ).all()
    users_by_id = {user.id: user for user in users}
    for customer_id in requested_ids:
        user = users_by_id.get(customer_id)
        if user is None or user.role != "customer":
            raise UnknownCustomerError(f"Customer {customer_id} was not found.")

    activity_rows = session.scalars(
        select(CustomerActivity)
        .where(
            CustomerActivity.user_id.in_(requested_ids),
            CustomerActivity.event_type == MODEL_FEATURES_EVENT_TYPE,
        )
        .order_by(CustomerActivity.created_at.desc(), CustomerActivity.id.desc())
    ).all()
    latest_snapshots: dict[int, CustomerActivity] = {}
    for activity in activity_rows:
        latest_snapshots.setdefault(activity.user_id, activity)

    feature_records: list[dict[str, object]] = []
    for customer_id in requested_ids:
        snapshot = latest_snapshots.get(customer_id)
        if snapshot is None or not isinstance(snapshot.event_metadata, dict):
            raise MissingCustomerFeaturesError(
                f"Customer {customer_id} has no model feature snapshot."
            )
        feature_records.append(snapshot.event_metadata)

    revenue_rows = session.execute(
        select(Order.user_id, func.sum(Order.total_amount))
        .where(
            Order.user_id.in_(requested_ids),
            Order.status == "completed",
        )
        .group_by(Order.user_id)
    ).all()
    revenue_decimal_by_id = {
        user_id: total or Decimal("0.00")
        for user_id, total in revenue_rows
    }
    for customer_id in requested_ids:
        revenue_decimal_by_id.setdefault(customer_id, Decimal("0.00"))
    # The decision engine accepts real numbers; retain Decimal values separately
    # for exact persistence in the Numeric customer_value column.
    revenue_by_id = {
        customer_id: float(revenue)
        for customer_id, revenue in revenue_decimal_by_id.items()
    }

    predictions = inference_service.predict_batch(requested_ids, feature_records)
    if len(predictions) != len(requested_ids):
        raise RuntimeError("Inference returned a different number of results than customers.")
    prediction_by_id = {prediction.customer_id: prediction for prediction in predictions}
    if set(prediction_by_id) != set(requested_ids):
        raise RuntimeError("Inference results did not match the requested customer IDs.")

    decision_result = decide_retention(
        [
            CustomerInput(
                customer_id=customer_id,
                churn_probability=prediction_by_id[customer_id].churn_probability,
                historical_revenue=revenue_by_id[customer_id],
            )
            for customer_id in requested_ids
        ],
        total_budget,
    )

    intervention_codes = {
        decision.selected_intervention for decision in decision_result.customers
    }
    offers = session.scalars(
        select(Offer).where(Offer.code.in_(intervention_codes))
    ).all()
    offers_by_code = {offer.code: offer for offer in offers}
    missing_offer_codes = intervention_codes - set(offers_by_code)
    if missing_offer_codes:
        raise RuntimeError(
            f"Approved offers are missing from the database: {sorted(missing_offer_codes)}"
        )

    try:
        current_interventions = session.scalars(
            select(RetentionIntervention).where(
                RetentionIntervention.user_id.in_(requested_ids),
                RetentionIntervention.status == ACTIVE_INTERVENTION_STATUS,
            )
        ).all()
        for intervention in current_interventions:
            intervention.status = SUPERSEDED_INTERVENTION_STATUS

        for prediction in predictions:
            session.add(
                RetentionPrediction(
                    user_id=prediction.customer_id,
                    churn_probability=Decimal(str(prediction.churn_probability)),
                    customer_value=revenue_decimal_by_id[prediction.customer_id],
                    model_version=prediction.model_version,
                )
            )

        for decision in decision_result.customers:
            offer = offers_by_code[decision.selected_intervention]
            assigned_at = utc_now()
            intervention = RetentionIntervention(
                user_id=decision.customer_id,
                offer_id=offer.id,
                intervention_cost=Decimal(
                    str(decision.estimated_intervention_cost)
                ),
                priority_score=Decimal(str(decision.priority_score)),
                decision_reason=decision.decision_explanation,
                status=(
                    ACTIVE_INTERVENTION_STATUS
                    if decision.selected_intervention != "NO_OFFER"
                    else NO_OFFER_INTERVENTION_STATUS
                ),
                created_at=assigned_at,
            )
            session.add(intervention)
            if decision.selected_intervention != "NO_OFFER":
                session.add(
                    RetentionOfferValidity(
                        intervention=intervention,
                        expires_at=assigned_at + timedelta(days=offer_validity_days),
                    )
                )

        if commit:
            session.commit()
    except Exception:
        session.rollback()
        raise

    return RetentionRefreshResult(
        predictions=predictions,
        decisions=decision_result,
    )


def evaluate_customer_retention(
    session: Session,
    inference_service: ChurnInferenceService,
    customer_id: int,
    total_budget: float,
    eligibility_threshold: float,
    *,
    commit: bool = True,
    offer_validity_days: int = DEFAULT_OFFER_VALIDITY_DAYS,
) -> CustomerEvaluationResult:
    """Infer and persist one customer's decision without reusing the full budget.

    Existing active paid assignments reserve their recorded cost. A selected
    customer who already has an active paid intervention is rejected so an
    unclaimed or redeemed offer cannot be replaced by this demonstration flow.
    """
    if isinstance(offer_validity_days, bool) or not 1 <= offer_validity_days <= 365:
        raise ValueError("offer_validity_days must be between 1 and 365 days.")
    # Centralize numeric validation and the threshold semantics in the policy.
    decide_retention(
        [], total_budget, eligibility_threshold=eligibility_threshold
    )

    user = session.scalar(
        select(User).where(User.id == customer_id, User.role == "customer")
    )
    if user is None:
        raise UnknownCustomerError(f"Customer {customer_id} was not found.")

    snapshot = session.scalar(
        select(CustomerActivity)
        .where(
            CustomerActivity.user_id == customer_id,
            CustomerActivity.event_type == MODEL_FEATURES_EVENT_TYPE,
        )
        .order_by(CustomerActivity.created_at.desc(), CustomerActivity.id.desc())
        .limit(1)
    )
    if snapshot is None or not isinstance(snapshot.event_metadata, dict):
        raise MissingCustomerFeaturesError(
            f"Customer {customer_id} has no model feature snapshot."
        )

    active_paid = session.execute(
        select(RetentionIntervention, Offer)
        .join(Offer, Offer.id == RetentionIntervention.offer_id)
        .where(
            RetentionIntervention.status == ACTIVE_INTERVENTION_STATUS,
            Offer.code != "NO_OFFER",
        )
    ).all()
    if any(intervention.user_id == customer_id for intervention, _ in active_paid):
        raise ExistingActiveInterventionError(
            "This customer already has an active paid offer; evaluation was not saved."
        )

    reserved_cost = sum(
        (intervention.intervention_cost for intervention, _ in active_paid),
        Decimal("0.00"),
    )
    available_budget = max(
        0.0, float(Decimal(str(total_budget)) - reserved_cost)
    )

    revenue = session.scalar(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(
            Order.user_id == customer_id,
            Order.status == "completed",
        )
    )
    historical_revenue = Decimal(str(revenue or 0))
    predictions = inference_service.predict_batch(
        [customer_id], [snapshot.event_metadata]
    )
    if len(predictions) != 1 or predictions[0].customer_id != customer_id:
        raise RuntimeError("Inference returned an unexpected customer result.")
    prediction = predictions[0]
    decisions = decide_retention(
        [
            CustomerInput(
                customer_id=customer_id,
                churn_probability=prediction.churn_probability,
                historical_revenue=float(historical_revenue),
            )
        ],
        available_budget,
        eligibility_threshold=eligibility_threshold,
    )
    decision = decisions.customers[0]
    offer = session.scalar(
        select(Offer).where(Offer.code == decision.selected_intervention)
    )
    if offer is None:
        raise RuntimeError(
            f"Approved offer {decision.selected_intervention} is missing from the database."
        )

    try:
        session.add(
            RetentionPrediction(
                user_id=customer_id,
                churn_probability=Decimal(str(prediction.churn_probability)),
                customer_value=historical_revenue,
                model_version=prediction.model_version,
            )
        )
        assigned_at = utc_now()
        intervention = RetentionIntervention(
            user_id=customer_id,
            offer_id=offer.id,
            intervention_cost=Decimal(str(decision.estimated_intervention_cost)),
            priority_score=Decimal(str(decision.priority_score)),
            decision_reason=decision.decision_explanation,
            status=(
                ACTIVE_INTERVENTION_STATUS
                if decision.selected_intervention != "NO_OFFER"
                else NO_OFFER_INTERVENTION_STATUS
            ),
            created_at=assigned_at,
        )
        session.add(intervention)
        if decision.selected_intervention != "NO_OFFER":
            session.add(
                RetentionOfferValidity(
                    intervention=intervention,
                    expires_at=assigned_at + timedelta(days=offer_validity_days),
                )
            )
        if commit:
            session.commit()
    except Exception:
        session.rollback()
        raise

    return CustomerEvaluationResult(
        prediction=prediction,
        decision=decisions,
        budget_available=available_budget,
        customer_email=user.email,
    )

