"""SQLAlchemy models for users, commerce activity, and retention records."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UTCDateTime, utc_now


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('customer', 'admin')", name="valid_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    activities: Mapped[list["CustomerActivity"]] = relationship(back_populates="user")
    predictions: Mapped[list["RetentionPrediction"]] = relationship(back_populates="user")
    interventions: Mapped[list["RetentionIntervention"]] = relationship(
        back_populates="user"
    )
    offer_claims: Mapped[list["RetentionOfferClaim"]] = relationship(
        back_populates="user"
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="nonnegative_price"),
        CheckConstraint("stock >= 0", name="nonnegative_stock"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")
    activities: Mapped[list["CustomerActivity"]] = relationship(back_populates="product")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="nonnegative_total_amount"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    user: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    pricing: Mapped["OrderPricing | None"] = relationship(
        back_populates="order", uselist=False
    )
    retention_redemption: Mapped["RetentionOfferRedemption | None"] = relationship(
        back_populates="order", uselist=False
    )


class OrderPricing(Base):
    """Server-calculated checkout breakdown for newly placed orders."""

    __tablename__ = "order_pricing"
    __table_args__ = (
        UniqueConstraint("order_id", name="one_pricing_breakdown_per_order"),
        CheckConstraint("subtotal_amount >= 0", name="nonnegative_subtotal_amount"),
        CheckConstraint("shipping_fee >= 0", name="nonnegative_shipping_fee"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 1", name="valid_demo_tax_rate"),
        CheckConstraint("tax_amount >= 0", name="nonnegative_tax_amount"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="pricing")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="one_product_line_per_order"),
        CheckConstraint("quantity > 0", name="positive_quantity"),
        CheckConstraint("unit_price >= 0", name="nonnegative_unit_price"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="order_items")


class CustomerActivity(Base):
    __tablename__ = "customer_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), nullable=True
    )
    # `metadata` is reserved by SQLAlchemy declarative models; the database
    # column keeps the requested name while Python code uses event_metadata.
    event_metadata: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    user: Mapped[User] = relationship(back_populates="activities")
    product: Mapped[Product | None] = relationship(back_populates="activities")


class RetentionPrediction(Base):
    __tablename__ = "retention_predictions"
    __table_args__ = (
        CheckConstraint(
            "churn_probability >= 0 AND churn_probability <= 1",
            name="valid_churn_probability",
        ),
        CheckConstraint("customer_value >= 0", name="nonnegative_customer_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    churn_probability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    customer_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)

    user: Mapped[User] = relationship(back_populates="predictions")


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("maximum_cost >= 0", name="nonnegative_maximum_cost"),
        CheckConstraint(
            "discount_percentage IS NULL OR "
            "(discount_percentage >= 0 AND discount_percentage <= 100)",
            name="valid_discount_percentage",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    discount_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    maximum_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    interventions: Mapped[list["RetentionIntervention"]] = relationship(
        back_populates="offer"
    )
    redemptions: Mapped[list["RetentionOfferRedemption"]] = relationship(
        back_populates="offer"
    )


class RetentionIntervention(Base):
    __tablename__ = "retention_interventions"
    __table_args__ = (
        CheckConstraint("intervention_cost >= 0", name="nonnegative_intervention_cost"),
        CheckConstraint("priority_score >= 0", name="nonnegative_priority_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), nullable=False)
    intervention_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    priority_score: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

    user: Mapped[User] = relationship(back_populates="interventions")
    offer: Mapped[Offer] = relationship(back_populates="interventions")
    claim: Mapped["RetentionOfferClaim | None"] = relationship(
        back_populates="intervention", uselist=False
    )
    validity: Mapped["RetentionOfferValidity | None"] = relationship(
        back_populates="intervention", uselist=False
    )
    redemption: Mapped["RetentionOfferRedemption | None"] = relationship(
        back_populates="intervention", uselist=False
    )


class RetentionOfferValidity(Base):
    """Persist the expiry fixed at offer assignment time."""

    __tablename__ = "retention_offer_validities"
    __table_args__ = (
        UniqueConstraint("intervention_id", name="one_validity_per_intervention"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intervention_id: Mapped[int] = mapped_column(
        ForeignKey("retention_interventions.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    intervention: Mapped[RetentionIntervention] = relationship(
        back_populates="validity"
    )


class RetentionOfferClaim(Base):
    """One simulated customer claim for a specific retention intervention."""

    __tablename__ = "retention_offer_claims"
    __table_args__ = (
        UniqueConstraint("intervention_id", name="one_claim_per_intervention"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intervention_id: Mapped[int] = mapped_column(
        ForeignKey("retention_interventions.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )

    intervention: Mapped[RetentionIntervention] = relationship(
        back_populates="claim"
    )
    user: Mapped[User] = relationship(back_populates="offer_claims")


class RetentionOfferRedemption(Base):
    """One-time application of a claimed retention offer to an order."""

    __tablename__ = "retention_offer_redemptions"
    __table_args__ = (
        UniqueConstraint("intervention_id", name="one_redemption_per_intervention"),
        UniqueConstraint("order_id", name="one_redemption_per_order"),
        CheckConstraint("discount_amount >= 0", name="nonnegative_redemption_discount"),
        CheckConstraint("shipping_discount >= 0", name="nonnegative_shipping_discount"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intervention_id: Mapped[int] = mapped_column(
        ForeignKey("retention_interventions.id"), nullable=False
    )
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    shipping_discount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00")
    )
    free_shipping_applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )

    intervention: Mapped[RetentionIntervention] = relationship(
        back_populates="redemption"
    )
    offer: Mapped[Offer] = relationship(back_populates="redemptions")
    order: Mapped[Order] = relationship(back_populates="retention_redemption")


class RetentionBudgetSetting(Base):
    """Persist the configured budget and the latest administrator allocation."""

    __tablename__ = "retention_budget_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_retention_budget_setting"),
        CheckConstraint("total_budget >= 0", name="nonnegative_retention_budget"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    total_budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    last_allocation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)

