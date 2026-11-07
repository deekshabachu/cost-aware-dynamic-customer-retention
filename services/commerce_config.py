"""Small, validated settings for local checkout and offer demonstrations."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os


CENT = Decimal("0.01")
DEFAULT_SHIPPING_FEE = Decimal("40.00")
DEFAULT_DEMO_TAX_RATE = Decimal("0.05")
DEFAULT_OFFER_VALIDITY_DAYS = 7


def _decimal_setting(name: str, default: Decimal) -> Decimal:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = Decimal(raw_value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a valid decimal amount or rate.") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number.")
    return value


@dataclass(frozen=True)
class CommerceConfig:
    shipping_fee: Decimal = DEFAULT_SHIPPING_FEE
    demo_tax_rate: Decimal = DEFAULT_DEMO_TAX_RATE
    offer_validity_days: int = DEFAULT_OFFER_VALIDITY_DAYS

    def __post_init__(self) -> None:
        if not self.shipping_fee.is_finite() or self.shipping_fee < 0:
            raise ValueError("Shipping fee must be a finite, non-negative amount.")
        if (
            not self.demo_tax_rate.is_finite()
            or self.demo_tax_rate < 0
            or self.demo_tax_rate > 1
        ):
            raise ValueError("Demo tax rate must be between 0 and 1.")
        if isinstance(self.offer_validity_days, bool) or not 1 <= self.offer_validity_days <= 365:
            raise ValueError("Offer validity must be between 1 and 365 days.")

    @classmethod
    def from_environment(cls) -> "CommerceConfig":
        """Read non-secret settings; defaults are local prototype assumptions."""
        raw_days = os.getenv("RETENTION_OFFER_VALIDITY_DAYS")
        try:
            validity_days = (
                DEFAULT_OFFER_VALIDITY_DAYS if raw_days is None else int(raw_days)
            )
        except ValueError as exc:
            raise ValueError("RETENTION_OFFER_VALIDITY_DAYS must be a whole number.") from exc
        return cls(
            shipping_fee=_decimal_setting("DEMO_SHIPPING_FEE", DEFAULT_SHIPPING_FEE).quantize(CENT),
            demo_tax_rate=_decimal_setting("DEMO_TAX_RATE", DEFAULT_DEMO_TAX_RATE),
            offer_validity_days=validity_days,
        )
