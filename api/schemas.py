"""Request and response schemas for the initial HTTP API."""

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt, field_validator

from api.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class StrictRequest(BaseModel):
    """Base request schema that rejects misspelled or unsupported fields."""

    model_config = ConfigDict(extra="forbid")


class EmailRequest(StrictRequest):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address.")
        return normalized


class CustomerRegistrationRequest(EmailRequest):
    name: str = Field(min_length=1, max_length=120)
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank.")
        return normalized


class LoginRequest(EmailRequest):
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class AdminLoginRequest(EmailRequest):
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class AuthenticatedUserResponse(BaseModel):
    id: int
    email: str


class ProductResponse(BaseModel):
    id: int
    name: str
    category: str
    price: str
    stock: int


class CheckoutLineRequest(StrictRequest):
    product_id: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(gt=0)


class CheckoutRequest(StrictRequest):
    items: list[CheckoutLineRequest] = Field(min_length=1)
    apply_retention_offer: bool = False

    @field_validator("items")
    @classmethod
    def reject_duplicate_products(
        cls, items: list[CheckoutLineRequest]
    ) -> list[CheckoutLineRequest]:
        product_ids = [item.product_id for item in items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Each product may appear only once in the cart.")
        return items


class OrderItemResponse(BaseModel):
    product_id: int
    product_name: str
    category: str
    quantity: int
    unit_price: str
    line_total: str


class OrderPricingResponse(BaseModel):
    subtotal_amount: str
    discount_amount: str = "0.00"
    applied_offer_name: str | None = None
    applied_offer_description: str | None = None
    shipping_fee: str
    shipping_discount_amount: str = "0.00"
    tax_rate_percent: float
    tax_amount: str
    total_amount: str


class OrderResponse(BaseModel):
    id: int
    status: str
    created_at: datetime
    total_amount: str
    pricing: OrderPricingResponse | None = None
    items: list[OrderItemResponse]


class OrderQuoteRequest(CheckoutRequest):
    """Use the same validated item contract for a non-persisted price quote."""


class OrderQuoteResponse(OrderPricingResponse):
    pass


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthenticatedUserResponse


class AdminAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PredictionRequest(StrictRequest):
    customer_id: str | int
    features: dict[str, Any]


class PredictionResponse(BaseModel):
    customer_id: str | int
    churn_probability: float
    model_version: str


class OfferResponse(BaseModel):
    code: str
    name: str
    description: str
    discount_percentage: float | None
    maximum_cost: float


class CustomerOfferDetailsResponse(BaseModel):
    name: str
    description: str
    discount_percentage: float | None


class AssignedRetentionInterventionResponse(BaseModel):
    created_at: datetime
    expires_at: datetime
    expired: bool
    offer: CustomerOfferDetailsResponse
    claimed: bool = False
    claimed_at: datetime | None = None
    redeemed: bool = False


class CustomerRetentionOfferResponse(BaseModel):
    assigned: bool
    intervention: AssignedRetentionInterventionResponse | None


class RetentionOfferClaimResponse(BaseModel):
    claimed: bool
    claimed_at: datetime | None
    message: str


class RetentionCustomerRequest(StrictRequest):
    customer_id: str | int
    churn_probability: float
    historical_revenue: float = Field(ge=0)


class RetentionDecisionRequest(StrictRequest):
    customers: list[RetentionCustomerRequest]
    total_budget: float = Field(ge=0)


class RetentionCustomerDecisionResponse(BaseModel):
    customer_id: str | int
    churn_probability: float
    historical_revenue: float
    priority_score: float
    eligible: bool
    selected_intervention: str
    estimated_intervention_cost: float
    decision_explanation: str
    budget_remaining: float


class RetentionSummaryResponse(BaseModel):
    initial_budget: float
    total_estimated_budget_allocated: float
    remaining_budget: float
    intervention_counts: dict[str, int]


class RetentionDecisionResponse(BaseModel):
    customers: list[RetentionCustomerDecisionResponse]
    summary: RetentionSummaryResponse


class RetentionRefreshRequest(StrictRequest):
    customer_ids: list[StrictInt] = Field(min_length=1)
    total_budget: float = Field(ge=0)


class RetentionRefreshResponse(BaseModel):
    predictions: list[PredictionResponse]
    decisions: list[RetentionCustomerDecisionResponse]
    summary: RetentionSummaryResponse


class AdminBudgetUpdateRequest(StrictRequest):
    total_budget: float = Field(ge=0, allow_inf_nan=False)


class AdminAllocationDecisionResponse(BaseModel):
    customer_id: int
    churn_probability: float | None
    historical_revenue: float | None
    priority_score: float | None
    intervention_code: str | None
    estimated_intervention_cost: float | None
    customer_email: str | None = None
    has_feature_snapshot: bool = True
    eligible: bool | None = None
    status: str | None = None
    preserved_existing_offer: bool = False
    preserved_redeemed_offer: bool = False
    new_offer_generated: bool = False


class AdminAllocationSummaryResponse(BaseModel):
    initial_budget: float
    total_estimated_budget_allocated: float
    remaining_budget: float
    intervention_counts: dict[str, int]
    customer_count: int
    skipped_customer_ids: list[int]
    created_at: datetime
    decisions: list[AdminAllocationDecisionResponse]
    # Populated for the safe bulk-evaluation endpoint. Optional fields keep
    # previously persisted single-allocation summaries backward compatible.
    eligibility_threshold: float | None = None
    total_accounts: int | None = None
    customers_evaluated: int | None = None
    customers_missing_feature_snapshot: int | None = None
    customers_below_threshold: int | None = None
    customers_eligible: int | None = None
    customers_receiving_no_offer: int | None = None
    existing_offers_preserved: int | None = None
    existing_redeemed_offers_preserved: int | None = None
    new_offers_generated: int | None = None
    total_new_offer_cost: float | None = None
    total_committed_reserved_cost: float | None = None


class AdminCurrentDecisionResponse(BaseModel):
    customer_id: int
    customer_email: str
    has_feature_snapshot: bool
    churn_probability: float | None
    historical_revenue: float | None
    priority_score: float | None
    intervention_code: str | None
    estimated_intervention_cost: float | None
    status: str | None
    claim_status: str | None
    claimed_at: datetime | None = None
    redeemed_order_id: int | None = None
    redemption_discount_amount: float | None = None
    redemption_shipping_discount: float | None = None
    free_shipping_applied: bool = False
    redeemed_at: datetime | None = None


class AdminDashboardResponse(BaseModel):
    total_customers: int
    customers_with_predictions: int
    customers_with_offers: int
    customers_with_no_offer: int
    intervention_counts: dict[str, int]
    customers_without_feature_snapshot: list[int]
    budget_configured: bool
    current_budget: float | None
    latest_allocation: AdminAllocationSummaryResponse | None
    current_decisions: list[AdminCurrentDecisionResponse]


class AdminBudgetResponse(BaseModel):
    budget_configured: bool
    current_budget: float


class AdminCustomerEvaluationRequest(StrictRequest):
    eligibility_threshold: float = Field(ge=0.10, le=0.90, allow_inf_nan=False)


class AdminBulkEvaluationRequest(StrictRequest):
    eligibility_threshold: float = Field(ge=0.10, le=0.90, allow_inf_nan=False)


class AdminCustomerEvaluationResponse(BaseModel):
    customer_id: int
    customer_email: str
    churn_probability: float
    model_version: str
    eligibility_threshold: float
    eligible: bool
    intervention_code: str
    estimated_intervention_cost: float
    budget_available: float
    budget_remaining: float
    budget_allowed_assignment: bool
    decision_explanation: str

