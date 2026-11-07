"""Prototype retention interventions and their configurable cost estimates.

These maximum costs are prototype assumptions for the mini-project. They are
not measured or verified real-world business costs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Intervention:
    """A retention offer and its maximum estimated cost in rupees."""

    code: str
    offer: str
    max_estimated_cost: float


# Configure intervention descriptions and cost estimates here in one place.
INTERVENTION_CATALOGUE: dict[str, Intervention] = {
    "NO_OFFER": Intervention(
        code="NO_OFFER",
        offer="No incentive",
        max_estimated_cost=0,
    ),
    "SMALL_DISCOUNT": Intervention(
        code="SMALL_DISCOUNT",
        offer="5% discount, capped at ₹100",
        max_estimated_cost=100,
    ),
    "LARGE_DISCOUNT": Intervention(
        code="LARGE_DISCOUNT",
        offer="10% discount, capped at ₹250",
        max_estimated_cost=250,
    ),
    "FREE_SHIPPING": Intervention(
        code="FREE_SHIPPING",
        offer="Waive shipping fee",
        max_estimated_cost=60,
    ),
}

