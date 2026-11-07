"""Validation for configurable local checkout and offer settings."""

from decimal import Decimal
import os
import unittest
from unittest.mock import patch

from services.commerce_config import CommerceConfig


class CommerceConfigTests(unittest.TestCase):
    def test_defaults_are_documented_local_assumptions(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = CommerceConfig.from_environment()
        self.assertEqual(config.shipping_fee, Decimal("40.00"))
        self.assertEqual(config.demo_tax_rate, Decimal("0.05"))
        self.assertEqual(config.offer_validity_days, 7)

    def test_values_can_be_configured_through_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEMO_SHIPPING_FEE": "25.50",
                "DEMO_TAX_RATE": "0.12",
                "RETENTION_OFFER_VALIDITY_DAYS": "14",
            },
            clear=True,
        ):
            config = CommerceConfig.from_environment()
        self.assertEqual(config.shipping_fee, Decimal("25.50"))
        self.assertEqual(config.demo_tax_rate, Decimal("0.12"))
        self.assertEqual(config.offer_validity_days, 14)

    def test_invalid_shipping_tax_and_expiry_values_are_rejected(self) -> None:
        for env_values in (
            {"DEMO_SHIPPING_FEE": "-1"},
            {"DEMO_TAX_RATE": "1.01"},
            {"RETENTION_OFFER_VALIDITY_DAYS": "0"},
        ):
            with self.subTest(env_values=env_values), patch.dict(
                os.environ, env_values, clear=True
            ), self.assertRaises(ValueError):
                CommerceConfig.from_environment()


if __name__ == "__main__":
    unittest.main()
