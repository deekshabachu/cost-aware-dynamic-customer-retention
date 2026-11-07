"""Explainable, budget-constrained customer retention decisions.

This module accepts churn probabilities and historical revenue as inputs. It
does not load the ML model or read from a database.
"""

from dataclasses import dataclass
import math
from numbers import Real
from typing import Sequence

from .interventions import INTERVENTION_CATALOGUE


ELIGIBILITY_THRESHOLD = 0.30
LARGE_DISCOUNT_CHURN_THRESHOLD = 0.70
LARGE_DISCOUNT_REVENUE_THRESHOLD = 2_000


@dataclass(frozen=True)
class CustomerInput:
    """Customer inputs required by the standalone decision policy."""

    customer_id: str | int
    churn_probability: float
    historical_revenue: float


@dataclass(frozen=True)
class CustomerDecision:
    """Decision details for one customer.

    ``budget_remaining`` is the balance at this customer's decision time.
    Ineligible customers are decided before allocation and retain the initial
    budget snapshot; eligible customers record their balance in priority order.
    """

    customer_id: str | int
    churn_probability: float
    historical_revenue: float
    priority_score: float
    eligible: bool
    selected_intervention: str
    estimated_intervention_cost: float
    decision_explanation: str
    budget_remaining: float


@dataclass(frozen=True)
class RetentionSummary:
    """Budget totals and intervention counts for a decision run."""

    initial_budget: float
    total_estimated_budget_allocated: float
    remaining_budget: float
    intervention_counts: dict[str, int]


@dataclass(frozen=True)
class DecisionResult:
    """Customer decisions in input order and their run-level summary."""

    customers: list[CustomerDecision]
    summary: RetentionSummary


def _validate_number(value: object, field_name: str) -> float:
    """Return a finite numeric input as float or raise a clear ValueError."""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite number.")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"{field_name} must be a finite number.")
    return numeric_value


def _validate_customer(customer: CustomerInput, index: int) -> None:
    """Validate one customer record before making any decisions."""

    if not isinstance(customer, CustomerInput):
        raise ValueError(
            f"customers[{index}] must be a CustomerInput instance."
        )
    if isinstance(customer.customer_id, bool) or not isinstance(
        customer.customer_id, (str, int)
    ):
        raise ValueError(
            f"customers[{index}].customer_id must be a string or integer."
        )
    if isinstance(customer.customer_id, str) and not customer.customer_id.strip():
        raise ValueError(f"customers[{index}].customer_id cannot be empty.")

    probability = _validate_number(
        customer.churn_probability,
        f"customers[{index}].churn_probability",
    )
    if not 0 <= probability <= 1:
        raise ValueError(
            f"customers[{index}].churn_probability must be between 0 and 1."
        )

    revenue = _validate_number(
        customer.historical_revenue,
        f"customers[{index}].historical_revenue",
    )
    if revenue < 0:
        raise ValueError(
            f"customers[{index}].historical_revenue cannot be negative."
        )


def _id_sort_key(customer_id: str | int) -> tuple[int, int | str]:
    """Create a deterministic tie-break key for supported customer IDs."""

    if isinstance(customer_id, int):
        return (0, customer_id)
    return (1, customer_id)


def _select_offer(customer: CustomerInput) -> tuple[str, str]:
    """Route an eligible customer to one offer using risk and revenue bands."""

    if customer.churn_probability >= LARGE_DISCOUNT_CHURN_THRESHOLD:
        if customer.historical_revenue >= LARGE_DISCOUNT_REVENUE_THRESHOLD:
            return (
                "LARGE_DISCOUNT",
                "High churn probability and historical revenue of at least "
                "₹2,000 qualify the customer for LARGE_DISCOUNT.",
            )
        return (
            "FREE_SHIPPING",
            "High churn probability with historical revenue below ₹2,000 "
            "routes the customer to FREE_SHIPPING.",
        )

    return (
        "SMALL_DISCOUNT",
        "Eligible customer below the high-risk threshold receives the "
        "default SMALL_DISCOUNT.",
    )


def decide_retention(
    customers: Sequence[CustomerInput],
    total_budget: Real,
    *,
    eligibility_threshold: Real = ELIGIBILITY_THRESHOLD,
) -> DecisionResult:
    """Assign offers under a finite budget and return decisions in input order.

    Eligible customers are allocated in descending churn-probability ×
    historical-revenue order. Customer ID breaks equal-priority ties. If an
    offer does not fit, that customer receives no offer and allocation
    continues to the next eligible customer.
    """

    initial_budget = _validate_number(total_budget, "total_budget")
    if initial_budget < 0:
        raise ValueError("total_budget cannot be negative.")
    threshold = _validate_number(eligibility_threshold, "eligibility_threshold")
    if not 0 <= threshold <= 1:
        raise ValueError("eligibility_threshold must be between 0 and 1.")

    customer_list = list(customers)
    for index, customer in enumerate(customer_list):
        _validate_customer(customer, index)

    ids = [customer.customer_id for customer in customer_list]
    if len(ids) != len(set(ids)):
        raise ValueError("customer_id values must be unique within customers.")

    # Each slot holds the output for the corresponding original input row.
    decisions: list[CustomerDecision | None] = [None] * len(customer_list)
    priority_scores = [
        float(customer.churn_probability) * float(customer.historical_revenue)
        for customer in customer_list
    ]

    eligible_indices: list[int] = []
    for index, customer in enumerate(customer_list):
        priority = priority_scores[index]
        if customer.churn_probability < threshold:
            no_offer = INTERVENTION_CATALOGUE["NO_OFFER"]
            decisions[index] = CustomerDecision(
                customer_id=customer.customer_id,
                churn_probability=float(customer.churn_probability),
                historical_revenue=float(customer.historical_revenue),
                priority_score=priority,
                eligible=False,
                selected_intervention=no_offer.code,
                estimated_intervention_cost=no_offer.max_estimated_cost,
                decision_explanation=(
                    f"Churn probability is below {threshold:.2f}; customer is not eligible "
                    "for a paid retention offer."
                ),
                budget_remaining=initial_budget,
            )
        else:
            eligible_indices.append(index)

    eligible_indices.sort(
        key=lambda index: (
            -priority_scores[index],
            _id_sort_key(customer_list[index].customer_id),
        )
    )

    remaining_budget = initial_budget
    for index in eligible_indices:
        customer = customer_list[index]
        priority = priority_scores[index]
        preferred_code, offer_reason = _select_offer(customer)
        preferred = INTERVENTION_CATALOGUE[preferred_code]

        if preferred.max_estimated_cost <= remaining_budget:
            chosen = preferred
            explanation = offer_reason
            remaining_budget = max(
                0.0,
                remaining_budget - chosen.max_estimated_cost,
            )
        else:
            chosen = INTERVENTION_CATALOGUE["NO_OFFER"]
            explanation = (
                f"{offer_reason} The selected offer costs up to "
                f"₹{preferred.max_estimated_cost:g}, which exceeds the "
                f"remaining budget of ₹{remaining_budget:g}; assigned NO_OFFER."
            )

        decisions[index] = CustomerDecision(
            customer_id=customer.customer_id,
            churn_probability=float(customer.churn_probability),
            historical_revenue=float(customer.historical_revenue),
            priority_score=priority,
            eligible=True,
            selected_intervention=chosen.code,
            estimated_intervention_cost=chosen.max_estimated_cost,
            decision_explanation=explanation,
            budget_remaining=remaining_budget,
        )

    completed_decisions = [decision for decision in decisions if decision is not None]
    intervention_counts = {
        code: sum(
            decision.selected_intervention == code
            for decision in completed_decisions
        )
        for code in INTERVENTION_CATALOGUE
    }
    allocated = sum(
        decision.estimated_intervention_cost
        for decision in completed_decisions
    )

    return DecisionResult(
        customers=completed_decisions,
        summary=RetentionSummary(
            initial_budget=initial_budget,
            total_estimated_budget_allocated=allocated,
            remaining_budget=remaining_budget,
            intervention_counts=intervention_counts,
        ),
    )

