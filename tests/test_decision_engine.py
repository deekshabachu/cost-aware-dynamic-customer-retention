"""Unit tests for the standalone cost-aware retention decision engine."""

import unittest

from retention import CustomerInput, decide_retention


class DecideRetentionTests(unittest.TestCase):
    def test_configurable_eligibility_threshold_is_inclusive(self) -> None:
        below, at_boundary = decide_retention(
            [
                CustomerInput("below", 0.19, 1_000),
                CustomerInput("boundary", 0.20, 1_000),
            ],
            total_budget=500,
            eligibility_threshold=0.20,
        ).customers
        self.assertFalse(below.eligible)
        self.assertEqual(below.selected_intervention, "NO_OFFER")
        self.assertTrue(at_boundary.eligible)
        self.assertEqual(at_boundary.selected_intervention, "SMALL_DISCOUNT")

    def test_low_risk_customer_receives_no_paid_offer(self) -> None:
        result = decide_retention(
            [CustomerInput("low", 0.29, 10_000)],
            total_budget=1_000,
        )

        decision = result.customers[0]
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.selected_intervention, "NO_OFFER")
        self.assertEqual(decision.estimated_intervention_cost, 0)

    def test_priority_orders_allocation_but_results_keep_input_order(self) -> None:
        result = decide_retention(
            [
                CustomerInput("lower", 0.50, 100),
                CustomerInput("higher", 0.90, 1_000),
            ],
            total_budget=60,
        )

        self.assertEqual(
            [decision.customer_id for decision in result.customers],
            ["lower", "higher"],
        )
        self.assertEqual(result.customers[0].priority_score, 50)
        self.assertEqual(result.customers[1].priority_score, 900)
        self.assertEqual(result.customers[0].selected_intervention, "NO_OFFER")
        self.assertEqual(result.customers[1].selected_intervention, "FREE_SHIPPING")

    def test_customer_id_breaks_equal_priority_ties_deterministically(self) -> None:
        result = decide_retention(
            [
                CustomerInput("B", 0.60, 100),
                CustomerInput("A", 0.50, 120),
            ],
            total_budget=100,
        )

        # Both priority scores equal 60; ID A is processed first.
        self.assertEqual(result.customers[1].budget_remaining, 0)
        self.assertEqual(result.customers[0].selected_intervention, "NO_OFFER")
        self.assertEqual(result.customers[1].selected_intervention, "SMALL_DISCOUNT")

    def test_integer_customer_ids_use_numeric_tie_break_order(self) -> None:
        result = decide_retention(
            [CustomerInput(10, 0.60, 100), CustomerInput(2, 0.50, 120)],
            total_budget=100,
        )

        self.assertEqual(result.customers[0].selected_intervention, "NO_OFFER")
        self.assertEqual(result.customers[1].selected_intervention, "SMALL_DISCOUNT")

    def test_large_discount_selected_at_risk_and_revenue_thresholds(self) -> None:
        result = decide_retention(
            [CustomerInput("high-value", 0.70, 2_000)],
            total_budget=250,
        )

        decision = result.customers[0]
        self.assertEqual(decision.selected_intervention, "LARGE_DISCOUNT")
        self.assertIn("at least ₹2,000", decision.decision_explanation)
        self.assertEqual(decision.estimated_intervention_cost, 250)

    def test_small_discount_selected_at_eligibility_boundary(self) -> None:
        result = decide_retention(
            [CustomerInput("regular", 0.30, 500)],
            total_budget=100,
        )

        decision = result.customers[0]
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.selected_intervention, "SMALL_DISCOUNT")
        self.assertEqual(decision.estimated_intervention_cost, 100)

    def test_free_shipping_selected_for_high_risk_below_revenue_boundary(self) -> None:
        result = decide_retention(
            [CustomerInput("high-risk-lower-value", 0.70, 1_999.99)],
            total_budget=60,
        )

        decision = result.customers[0]
        self.assertEqual(decision.selected_intervention, "FREE_SHIPPING")
        self.assertEqual(decision.estimated_intervention_cost, 60)
        self.assertIn("below ₹2,000", decision.decision_explanation)

    def test_large_offer_skipped_and_allocation_continues_to_later_customer(self) -> None:
        result = decide_retention(
            [
                CustomerInput("small", 0.50, 1_000),
                CustomerInput("large", 0.90, 2_000),
                CustomerInput("ineligible", 0.20, 10_000),
            ],
            total_budget=100,
        )

        # Results stay in input order, while the large offer is considered first.
        small, large, ineligible = result.customers
        self.assertEqual(small.selected_intervention, "SMALL_DISCOUNT")
        self.assertEqual(small.budget_remaining, 0)
        self.assertEqual(large.selected_intervention, "NO_OFFER")
        self.assertEqual(large.estimated_intervention_cost, 0)
        self.assertIn("exceeds the remaining budget", large.decision_explanation)
        self.assertEqual(large.budget_remaining, 100)
        self.assertFalse(ineligible.eligible)
        self.assertEqual(ineligible.selected_intervention, "NO_OFFER")
        self.assertEqual(ineligible.budget_remaining, 100)
        self.assertEqual(result.summary.total_estimated_budget_allocated, 100)
        self.assertEqual(result.summary.remaining_budget, 0)

    def test_insufficient_budget_skips_eligible_customers(self) -> None:
        result = decide_retention(
            [
                CustomerInput("top", 0.90, 1_000),
                CustomerInput("next", 0.50, 100),
            ],
            total_budget=59,
        )

        by_id = {decision.customer_id: decision for decision in result.customers}
        self.assertEqual(by_id["top"].selected_intervention, "NO_OFFER")
        self.assertEqual(by_id["top"].budget_remaining, 59)
        self.assertEqual(by_id["next"].selected_intervention, "NO_OFFER")
        self.assertEqual(by_id["next"].budget_remaining, 59)
        self.assertIn("assigned NO_OFFER", by_id["next"].decision_explanation)

    def test_budget_never_becomes_negative(self) -> None:
        result = decide_retention(
            [
                CustomerInput("a", 0.90, 1_000),
                CustomerInput("b", 0.80, 1_000),
                CustomerInput("c", 0.70, 2_000),
            ],
            total_budget=100,
        )

        self.assertTrue(
            all(decision.budget_remaining >= 0 for decision in result.customers)
        )
        self.assertGreaterEqual(result.summary.remaining_budget, 0)
        self.assertEqual(result.summary.total_estimated_budget_allocated, 60)

    def test_zero_budget_assigns_no_paid_offers(self) -> None:
        result = decide_retention(
            [CustomerInput("eligible", 0.90, 5_000)],
            total_budget=0,
        )

        decision = result.customers[0]
        self.assertEqual(decision.selected_intervention, "NO_OFFER")
        self.assertEqual(decision.estimated_intervention_cost, 0)
        self.assertEqual(decision.budget_remaining, 0)
        self.assertEqual(result.summary.total_estimated_budget_allocated, 0)

    def test_empty_customers_returns_zero_counts_and_full_budget(self) -> None:
        result = decide_retention([], total_budget=500)

        self.assertEqual(result.customers, [])
        self.assertEqual(result.summary.initial_budget, 500)
        self.assertEqual(result.summary.remaining_budget, 500)
        self.assertEqual(result.summary.total_estimated_budget_allocated, 0)
        self.assertEqual(
            result.summary.intervention_counts,
            {
                "NO_OFFER": 0,
                "SMALL_DISCOUNT": 0,
                "LARGE_DISCOUNT": 0,
                "FREE_SHIPPING": 0,
            },
        )

    def test_invalid_churn_probability_raises_value_error(self) -> None:
        for probability in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(probability=probability):
                with self.assertRaisesRegex(ValueError, "churn_probability"):
                    decide_retention(
                        [CustomerInput("bad", probability, 0)],
                        total_budget=100,
                    )

    def test_negative_revenue_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "historical_revenue cannot be negative"):
            decide_retention(
                [CustomerInput("bad", 0.5, -1)],
                total_budget=100,
            )

    def test_negative_budget_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "total_budget cannot be negative"):
            decide_retention([], total_budget=-1)


if __name__ == "__main__":
    unittest.main()
