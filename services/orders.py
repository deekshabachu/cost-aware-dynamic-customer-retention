"""Checkout and order-history operations for authenticated customers."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, joinedload

from database.base import utc_now
from database.models import (
    Order,
    OrderItem,
    OrderPricing,
    Product,
    RetentionIntervention,
    RetentionOfferRedemption,
)
from services.commerce_config import CommerceConfig


SIMULATED_COMPLETED_STATUS = "completed"
CENT = Decimal("0.01")
MAXIMUM_ORDER_TOTAL = Decimal("9999999999.99")


@dataclass(frozen=True)
class OrderQuote:
    """Server-calculated product lines and checkout totals."""

    product_lines: list[tuple[Product, int, Decimal]]
    subtotal_amount: Decimal
    discount_amount: Decimal
    applied_offer_code: str | None
    applied_offer_name: str | None
    applied_offer_description: str | None
    shipping_fee: Decimal
    shipping_discount_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total_amount: Decimal


class UnknownProductsError(ValueError):
    """Raised when a cart refers to product IDs absent from the catalogue."""


class UnavailableProductsError(ValueError):
    """Raised when requested quantities exceed currently listed stock."""


class RetentionOfferUnavailableError(ValueError):
    """Raised when the signed-in customer cannot redeem an offer."""


def _eligible_retention_intervention(
    session: Session,
    customer_id: int,
    pricing_config: CommerceConfig,
) -> RetentionIntervention:
    intervention = session.scalar(
        select(RetentionIntervention)
        .options(
            joinedload(RetentionIntervention.offer),
            joinedload(RetentionIntervention.claim),
            joinedload(RetentionIntervention.validity),
            joinedload(RetentionIntervention.redemption),
        )
        .where(
            RetentionIntervention.user_id == customer_id,
            RetentionIntervention.status == "active",
        )
        .order_by(RetentionIntervention.created_at.desc(), RetentionIntervention.id.desc())
        .limit(1)
    )
    if (
        intervention is None
        or intervention.offer.code == "NO_OFFER"
        or not intervention.offer.active
        or intervention.claim is None
        or intervention.claim.user_id != customer_id
        or intervention.redemption is not None
    ):
        raise RetentionOfferUnavailableError(
            "There is no claimed retention offer available for this order."
        )
    expires_at = (
        intervention.validity.expires_at
        if intervention.validity is not None
        else intervention.created_at
        + timedelta(days=pricing_config.offer_validity_days)
    )
    if expires_at <= utc_now():
        raise RetentionOfferUnavailableError("Your retention offer has expired.")
    return intervention


def calculate_order_quote(
    session: Session,
    cart_lines: list[tuple[int, int]],
    pricing_config: CommerceConfig,
    *,
    customer_id: int | None = None,
    apply_retention_offer: bool = False,
) -> OrderQuote:
    """Calculate current database prices, configured charges, and a validated offer."""
    if not cart_lines:
        raise ValueError("The cart must contain at least one item.")

    product_ids = [product_id for product_id, _ in cart_lines]
    products = session.scalars(select(Product).where(Product.id.in_(product_ids))).all()
    products_by_id = {product.id: product for product in products}
    missing_ids = [product_id for product_id in product_ids if product_id not in products_by_id]
    if missing_ids:
        raise UnknownProductsError(
            f"Product IDs were not found: {', '.join(map(str, missing_ids))}."
        )

    product_lines: list[tuple[Product, int, Decimal]] = []
    subtotal = Decimal("0.00")
    for product_id, quantity in cart_lines:
        product = products_by_id[product_id]
        if product.stock <= 0 or quantity > product.stock:
            raise UnavailableProductsError(
                f"{product.name} is not available in the requested quantity."
            )
        unit_price = Decimal(product.price).quantize(CENT, rounding=ROUND_HALF_UP)
        subtotal += unit_price * quantity
        if subtotal > MAXIMUM_ORDER_TOTAL:
            raise ValueError("The order exceeds the maximum supported total.")
        product_lines.append((product, quantity, unit_price))

    subtotal = subtotal.quantize(CENT, rounding=ROUND_HALF_UP)
    shipping = pricing_config.shipping_fee.quantize(CENT, rounding=ROUND_HALF_UP)
    discount = Decimal("0.00")
    shipping_discount = Decimal("0.00")
    intervention = None
    if apply_retention_offer:
        if customer_id is None:
            raise RetentionOfferUnavailableError("A signed-in customer is required.")
        intervention = _eligible_retention_intervention(
            session, customer_id, pricing_config
        )
        offer = intervention.offer
        if offer.code in {"SMALL_DISCOUNT", "LARGE_DISCOUNT"}:
            if offer.discount_percentage is None:
                raise RetentionOfferUnavailableError(
                    "This retention offer is not configured for checkout."
                )
            requested_discount = (
                subtotal * Decimal(offer.discount_percentage) / Decimal("100")
            ).quantize(CENT, rounding=ROUND_HALF_UP)
            discount = min(
                requested_discount,
                Decimal(offer.maximum_cost).quantize(CENT),
                subtotal,
            )
        elif offer.code == "FREE_SHIPPING":
            shipping_discount = shipping
        else:
            raise RetentionOfferUnavailableError(
                "This retention offer cannot be applied at checkout."
            )

    discounted_subtotal = subtotal - discount
    tax = (discounted_subtotal * pricing_config.demo_tax_rate).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    total = discounted_subtotal + shipping - shipping_discount + tax
    if total > MAXIMUM_ORDER_TOTAL:
        raise ValueError("The order exceeds the maximum supported total.")
    return OrderQuote(
        product_lines=product_lines,
        subtotal_amount=subtotal,
        discount_amount=discount,
        applied_offer_code=intervention.offer.code if intervention is not None else None,
        applied_offer_name=intervention.offer.name if intervention is not None else None,
        applied_offer_description=(
            intervention.offer.description if intervention is not None else None
        ),
        shipping_fee=shipping,
        shipping_discount_amount=shipping_discount,
        tax_rate=pricing_config.demo_tax_rate,
        tax_amount=tax,
        total_amount=total.quantize(CENT, rounding=ROUND_HALF_UP),
    )


def create_simulated_order(
    session: Session,
    customer_id: int,
    cart_lines: list[tuple[int, int]],
    *,
    commit: bool = True,
    pricing_config: CommerceConfig | None = None,
    apply_retention_offer: bool = False,
) -> Order:
    """Create one simulated completed purchase using database prices.

    The order is marked completed so it contributes to the existing
    completed-order revenue calculation. This represents a simulated purchase
    for the prototype; it does not represent a payment or delivery.
    """
    try:
        # Scripted historical demo orders retain their original subtotal-only
        # behaviour unless an application checkout explicitly supplies config.
        has_pricing_config = pricing_config is not None
        effective_config = pricing_config or CommerceConfig(
            shipping_fee=Decimal("0.00"), demo_tax_rate=Decimal("0.00")
        )
        quote = calculate_order_quote(
            session,
            cart_lines,
            effective_config,
            customer_id=customer_id,
            apply_retention_offer=apply_retention_offer,
        )
        order_items: list[OrderItem] = []
        for product, quantity, unit_price in quote.product_lines:
            order_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )

        order = Order(
            user_id=customer_id,
            total_amount=quote.total_amount,
            status=SIMULATED_COMPLETED_STATUS,
            pricing=(
                OrderPricing(
                    subtotal_amount=quote.subtotal_amount,
                    shipping_fee=quote.shipping_fee,
                    tax_rate=quote.tax_rate,
                    tax_amount=quote.tax_amount,
                )
                if has_pricing_config
                else None
            ),
        )
        session.add(order)
        session.flush()
        for order_item in order_items:
            order_item.order_id = order.id
        session.add_all(order_items)
        session.flush()
        if apply_retention_offer:
            intervention = _eligible_retention_intervention(
                session, customer_id, effective_config
            )
            redemption = RetentionOfferRedemption(
                intervention_id=intervention.id,
                offer_id=intervention.offer_id,
                order_id=order.id,
                discount_amount=quote.discount_amount,
                shipping_discount=quote.shipping_discount_amount,
                free_shipping_applied=quote.applied_offer_code == "FREE_SHIPPING",
            )
            session.add(redemption)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise RetentionOfferUnavailableError(
                    "This retention offer has already been redeemed."
                ) from exc
        saved_order = session.execute(
            select(Order)
            .where(Order.id == order.id)
            .options(
                joinedload(Order.items).joinedload(OrderItem.product),
                joinedload(Order.pricing),
                joinedload(Order.retention_redemption).joinedload(
                    RetentionOfferRedemption.offer
                ),
            )
        ).unique().scalar_one()
        if commit:
            session.commit()
        return saved_order
    except OperationalError as exc:
        session.rollback()
        if apply_retention_offer and "locked" in str(exc.orig).lower():
            raise RetentionOfferUnavailableError(
                "Another checkout is using this offer. Refresh your order and try again."
            ) from exc
        raise
    except Exception:
        session.rollback()
        raise


def get_customer_orders(session: Session, customer_id: int) -> list[Order]:
    """Return only this customer's orders, newest first, with item products."""
    return list(
        session.scalars(
            select(Order)
            .where(Order.user_id == customer_id)
            .options(
                joinedload(Order.items).joinedload(OrderItem.product),
                joinedload(Order.pricing),
                joinedload(Order.retention_redemption).joinedload(
                    RetentionOfferRedemption.offer
                ),
            )
            .order_by(Order.created_at.desc(), Order.id.desc())
        ).unique().all()
    )
