# Local demo order histories

`python -m scripts.seed_demo_order_histories` manually adds simulated completed orders for seed-verified Customers 03–05 and 07–09. Customer 06 is deliberately kept order-free. Customers 01 and 02 are never changed by this script.

The script uses the existing checkout order service, reads product IDs and prices from the database catalogue, and creates matching order items and completed order totals. It does not process payment, decrement inventory, refresh retention decisions, or run during application startup.

The order table has no metadata column. To avoid a database migration, each order created by this script has a companion `CustomerActivity` marker (`demo_order_history_seed`) with a script-specific namespace, order ID, and plan index. The order and marker are committed atomically. Rerunning the script reuses those markers and creates no duplicates. Do not remove these marker activity records if you want repeat runs to remain idempotent.

Run `python -m scripts.verify_demo_customers` for a read-only check of all nine namespaced customer identities, customer roles, feature snapshots against the saved inference artifacts, order/revenue totals, and latest offer state. The verifier does not read passwords or attempt login; use the existing login flow for interactive authentication checks.
