"""Order API tests use isolated, temporary SQLite databases."""

from decimal import Decimal
from datetime import timedelta
from pathlib import Path
import secrets
import re
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import create_access_token, hash_password
from api.main import create_app
from database.config import create_database_engine
from database.initialize import initialize_database
from database.base import utc_now
from database.models import (
    Offer,
    Order,
    OrderItem,
    Product,
    RetentionIntervention,
    RetentionOfferClaim,
    RetentionOfferRedemption,
    RetentionOfferValidity,
    User,
)
from services.commerce_config import CommerceConfig
from scripts.seed_store_products import DEMO_PRODUCTS, seed_store_products


class OrderApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_database_engine(
            f"sqlite:///{(Path(self.temp.name) / 'orders.db').as_posix()}"
        )
        initialize_database(self.engine)
        self.secret = secrets.token_urlsafe(48)
        with Session(self.engine) as db:
            self.customer = User(
                name="Customer", email="customer@test.invalid",
                password_hash=hash_password("a-long-test-password"), role="customer",
            )
            self.other = User(
                name="Other", email="other@test.invalid",
                password_hash=hash_password("another-long-password"), role="customer",
            )
            self.milk = Product(
                name="Milk", category="Dairy", description="Milk",
                price=Decimal("12.50"), stock=10,
            )
            self.bread = Product(
                name="Bread", category="Bakery", description="Bread",
                price=Decimal("3.25"), stock=2,
            )
            db.add_all([self.customer, self.other, self.milk, self.bread])
            db.commit()
            self.customer_id, self.other_id = self.customer.id, self.other.id
            self.milk_id, self.bread_id = self.milk.id, self.bread.id
        self.client_context = TestClient(create_app(
            database_engine=self.engine, inference_service=object(),
            auth_secret_key=self.secret,
            commerce_config=CommerceConfig(),
        ))
        self.client = self.client_context.__enter__()
        self.headers = {"Authorization": f"Bearer {create_access_token(self.customer_id, self.secret)}"}
        self.other_headers = {"Authorization": f"Bearer {create_access_token(self.other_id, self.secret)}"}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.engine.dispose()
        self.temp.cleanup()

    def assign_claimed_offer(self, customer_id=None, code="SMALL_DISCOUNT", *, claimed=True, expires_at=None):
        customer_id = self.customer_id if customer_id is None else customer_id
        with Session(self.engine) as db:
            offer = db.scalar(select(Offer).where(Offer.code == code))
            intervention = RetentionIntervention(
                user_id=customer_id,
                offer_id=offer.id,
                intervention_cost=offer.maximum_cost,
                priority_score=Decimal("20.0000"),
                decision_reason="Test fixture.",
                status="active",
            )
            db.add(intervention)
            db.flush()
            db.add(RetentionOfferValidity(
                intervention_id=intervention.id,
                expires_at=expires_at or utc_now() + timedelta(days=7),
            ))
            if claimed:
                db.add(RetentionOfferClaim(
                    intervention_id=intervention.id,
                    user_id=customer_id,
                ))
            db.commit()
            return intervention.id

    def test_checkout_and_history_require_authentication(self):
        self.assertEqual(self.client.get("/orders").status_code, 401)
        self.assertEqual(
            self.client.post("/orders/checkout", json={"items": [{"product_id": self.milk_id, "quantity": 1}]}).status_code,
            401,
        )

    def test_checkout_uses_db_prices_and_returns_simulated_completed_confirmation(self):
        response = self.client.post("/orders/checkout", headers=self.headers, json={"items": [
            {"product_id": self.milk_id, "quantity": 2},
            {"product_id": self.bread_id, "quantity": 1},
        ]})
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        self.assertEqual(order["status"], "completed")
        self.assertEqual(order["total_amount"], "69.66")
        self.assertEqual(
            order["pricing"],
            {
                "subtotal_amount": "28.25",
                "discount_amount": "0.00",
                "applied_offer_name": None,
                "applied_offer_description": None,
                "shipping_fee": "40.00",
                "shipping_discount_amount": "0.00",
                "tax_rate_percent": 5.0,
                "tax_amount": "1.41",
                "total_amount": "69.66",
            },
        )
        self.assertEqual([i["unit_price"] for i in order["items"]], ["12.50", "3.25"])
        self.assertEqual([i["line_total"] for i in order["items"]], ["25.00", "3.25"])
        self.assertTrue(order["created_at"].endswith(("Z", "+00:00")))
        with Session(self.engine) as db:
            saved = db.get(Order, order["id"])
            self.assertEqual(saved.user_id, self.customer_id)
            self.assertEqual(saved.total_amount, Decimal("69.66"))
            self.assertEqual(saved.pricing.subtotal_amount, Decimal("28.25"))
            self.assertEqual(saved.pricing.shipping_fee, Decimal("40.00"))
            self.assertEqual(saved.pricing.tax_amount, Decimal("1.41"))
            self.assertEqual(len(saved.items), 2)

    def test_price_quote_uses_database_prices_without_creating_an_order(self):
        response = self.client.post("/orders/quote", headers=self.headers, json={
            "items": [{"product_id": self.milk_id, "quantity": 2}],
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["subtotal_amount"], "25.00")
        self.assertEqual(response.json()["shipping_fee"], "40.00")
        self.assertEqual(response.json()["tax_amount"], "1.25")
        self.assertEqual(response.json()["total_amount"], "66.25")
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 0)

    def test_shipping_and_demo_tax_are_configurable_and_backend_quote_is_authoritative(self):
        config = CommerceConfig(
            shipping_fee=Decimal("10.00"),
            demo_tax_rate=Decimal("0.10"),
            offer_validity_days=7,
        )
        client_context = TestClient(create_app(
            database_engine=self.engine,
            inference_service=object(),
            auth_secret_key=self.secret,
            commerce_config=config,
        ))
        with client_context as client:
            quote = client.post("/orders/quote", headers=self.headers, json={
                "items": [{"product_id": self.milk_id, "quantity": 1}],
            })
            self.assertEqual(quote.status_code, 200, quote.text)
            self.assertEqual(quote.json()["tax_rate_percent"], 10.0)
            self.assertEqual(quote.json()["tax_amount"], "1.25")
            self.assertEqual(quote.json()["total_amount"], "23.75")
            order = client.post("/orders/checkout", headers=self.headers, json={
                "items": [{"product_id": self.milk_id, "quantity": 1}],
            })
            self.assertEqual(order.status_code, 201, order.text)
            self.assertEqual(order.json()["total_amount"], quote.json()["total_amount"])

    def test_own_claimed_small_discount_is_calculated_and_redeemed_with_order(self):
        intervention_id = self.assign_claimed_offer(code="SMALL_DISCOUNT")
        body = {"items": [{"product_id": self.milk_id, "quantity": 2}], "apply_retention_offer": True}
        quote = self.client.post("/orders/quote", headers=self.headers, json=body)
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertEqual(quote.json()["subtotal_amount"], "25.00")
        self.assertEqual(quote.json()["discount_amount"], "1.25")
        self.assertEqual(quote.json()["tax_amount"], "1.19")
        self.assertEqual(quote.json()["total_amount"], "64.94")

        response = self.client.post("/orders/checkout", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["total_amount"], quote.json()["total_amount"])
        self.assertEqual(response.json()["pricing"]["applied_offer_name"], "Small discount")
        with Session(self.engine) as db:
            redemption = db.scalar(select(RetentionOfferRedemption).where(
                RetentionOfferRedemption.intervention_id == intervention_id
            ))
            self.assertIsNotNone(redemption)
            self.assertEqual(redemption.order_id, response.json()["id"])
            self.assertEqual(redemption.offer_id, redemption.intervention.offer_id)
            self.assertEqual(redemption.discount_amount, Decimal("1.25"))
            self.assertFalse(redemption.free_shipping_applied)

    def test_small_discount_is_capped_at_configured_maximum(self):
        self.assign_claimed_offer(code="SMALL_DISCOUNT")
        with Session(self.engine) as db:
            db.get(Product, self.milk_id).price = Decimal("3000.00")
            db.commit()
        response = self.client.post("/orders/quote", headers=self.headers, json={
            "items": [{"product_id": self.milk_id, "quantity": 1}],
            "apply_retention_offer": True,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["discount_amount"], "100.00")
        self.assertEqual(response.json()["tax_amount"], "145.00")
        self.assertEqual(response.json()["total_amount"], "3085.00")

    def test_large_discount_uses_configured_percentage_and_maximum_cost(self):
        self.assign_claimed_offer(code="LARGE_DISCOUNT")
        with Session(self.engine) as db:
            db.get(Product, self.milk_id).price = Decimal("3000.00")
            db.commit()
        response = self.client.post("/orders/checkout", headers=self.headers, json={
            "items": [{"product_id": self.milk_id, "quantity": 1}],
            "apply_retention_offer": True,
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["pricing"]["discount_amount"], "250.00")
        self.assertEqual(response.json()["pricing"]["tax_amount"], "137.50")
        self.assertEqual(response.json()["total_amount"], "2927.50")

    def test_free_shipping_waives_shipping_and_persists_redemption(self):
        intervention_id = self.assign_claimed_offer(code="FREE_SHIPPING")
        response = self.client.post("/orders/checkout", headers=self.headers, json={
            "items": [{"product_id": self.milk_id, "quantity": 1}],
            "apply_retention_offer": True,
        })
        self.assertEqual(response.status_code, 201, response.text)
        pricing = response.json()["pricing"]
        self.assertEqual(pricing["shipping_fee"], "40.00")
        self.assertEqual(pricing["shipping_discount_amount"], "40.00")
        self.assertEqual(response.json()["total_amount"], "13.13")
        with Session(self.engine) as db:
            redemption = db.scalar(select(RetentionOfferRedemption).where(
                RetentionOfferRedemption.intervention_id == intervention_id
            ))
            self.assertTrue(redemption.free_shipping_applied)
            self.assertEqual(redemption.shipping_discount, Decimal("40.00"))
            self.assertIsNotNone(redemption.redeemed_at)

    def test_free_shipping_waives_the_configured_shipping_fee(self):
        self.assign_claimed_offer(code="FREE_SHIPPING")
        context = TestClient(create_app(
            database_engine=self.engine,
            inference_service=object(),
            auth_secret_key=self.secret,
            commerce_config=CommerceConfig(
                shipping_fee=Decimal("80.00"),
                demo_tax_rate=Decimal("0.05"),
                offer_validity_days=7,
            ),
        ))
        with context as client:
            response = client.post("/orders/quote", headers=self.headers, json={
                "items": [{"product_id": self.milk_id, "quantity": 1}],
                "apply_retention_offer": True,
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["shipping_fee"], "80.00")
        self.assertEqual(response.json()["shipping_discount_amount"], "80.00")
        self.assertEqual(response.json()["total_amount"], "13.13")

    def test_no_offer_unclaimed_expired_and_other_customers_offer_are_rejected(self):
        no_assigned_offer = self.client.post("/orders/quote", headers=self.headers, json={
            "items": [{"product_id": self.milk_id, "quantity": 1}],
            "apply_retention_offer": True,
        })
        self.assertEqual(no_assigned_offer.status_code, 409)
        cases = [
            (self.customer_id, "FREE_SHIPPING", False, utc_now() + timedelta(days=7)),
            (self.customer_id, "FREE_SHIPPING", True, utc_now() - timedelta(seconds=1)),
            (self.other_id, "FREE_SHIPPING", True, utc_now() + timedelta(days=7)),
        ]
        for customer_id, code, claimed, expiry in cases:
            with self.subTest(customer_id=customer_id, claimed=claimed, expiry=expiry):
                self.assign_claimed_offer(customer_id, code, claimed=claimed, expires_at=expiry)
                response = self.client.post("/orders/quote", headers=self.headers, json={
                    "items": [{"product_id": self.milk_id, "quantity": 1}],
                    "apply_retention_offer": True,
                })
                self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 0)
            self.assertEqual(db.query(RetentionOfferRedemption).count(), 0)

    def test_redeemed_offer_cannot_be_used_twice(self):
        intervention_id = self.assign_claimed_offer(code="FREE_SHIPPING")
        payload = {"items": [{"product_id": self.milk_id, "quantity": 1}], "apply_retention_offer": True}
        first = self.client.post("/orders/checkout", headers=self.headers, json=payload)
        second = self.client.post("/orders/checkout", headers=self.headers, json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 1)
            self.assertEqual(db.query(RetentionOfferRedemption).filter_by(intervention_id=intervention_id).count(), 1)

    def test_database_unique_constraint_prevents_duplicate_redemption_rows(self):
        intervention_id = self.assign_claimed_offer(code="SMALL_DISCOUNT")
        first = self.client.post("/orders/checkout", headers=self.headers, json={
            "items": [{"product_id": self.milk_id, "quantity": 1}],
            "apply_retention_offer": True,
        })
        self.assertEqual(first.status_code, 201, first.text)
        with Session(self.engine) as db:
            second_order = Order(
                user_id=self.customer_id,
                total_amount=Decimal("1.00"),
                status="completed",
            )
            db.add(second_order)
            db.flush()
            db.add(RetentionOfferRedemption(
                intervention_id=intervention_id,
                offer_id=db.scalar(select(Offer.id).where(Offer.code == "SMALL_DISCOUNT")),
                order_id=second_order.id,
                discount_amount=Decimal("0.01"),
                shipping_discount=Decimal("0.00"),
                free_shipping_applied=False,
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 1)
            self.assertEqual(db.query(RetentionOfferRedemption).count(), 1)

    def test_removing_offer_restores_normal_quote_and_client_cannot_submit_amounts(self):
        self.assign_claimed_offer(code="SMALL_DISCOUNT")
        lines = [{"product_id": self.milk_id, "quantity": 1}]
        discounted = self.client.post("/orders/quote", headers=self.headers, json={
            "items": lines, "apply_retention_offer": True,
        }).json()
        normal = self.client.post("/orders/quote", headers=self.headers, json={"items": lines}).json()
        self.assertEqual(discounted["discount_amount"], "0.63")
        self.assertEqual(normal["discount_amount"], "0.00")
        self.assertEqual(normal["shipping_fee"], "40.00")
        self.assertEqual(normal["total_amount"], "53.13")
        for payload in (
            {"items": lines, "apply_retention_offer": True, "discount_amount": 0},
            {"items": lines, "apply_retention_offer": True, "shipping_fee": 0},
            {"items": lines, "apply_retention_offer": True, "offer_id": 123},
        ):
            self.assertEqual(self.client.post("/orders/checkout", headers=self.headers, json=payload).status_code, 422)
        for extra in ({"discount_amount": 0}, {"shipping_fee": 0}, {"offer_id": 123}):
            payload = {"items": lines, "apply_retention_offer": True, **extra}
            self.assertEqual(self.client.post("/orders/quote", headers=self.headers, json=payload).status_code, 422)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 0)

    def test_offer_redemption_rolls_back_when_order_items_fail(self):
        self.assign_claimed_offer(code="SMALL_DISCOUNT")
        with Session(self.engine) as db:
            db.execute(text(
                "CREATE TRIGGER reject_offer_item BEFORE INSERT ON order_items "
                f"WHEN NEW.product_id = {self.milk_id} "
                "BEGIN SELECT RAISE(ABORT, 'test rollback'); END"
            ))
            db.commit()
        with self.assertLogs("api.main", level="ERROR"):
            response = self.client.post("/orders/checkout", headers=self.headers, json={
                "items": [{"product_id": self.milk_id, "quantity": 1}],
                "apply_retention_offer": True,
            })
        self.assertEqual(response.status_code, 500)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 0)
            self.assertEqual(db.query(RetentionOfferRedemption).count(), 0)

    def test_product_listing_returns_database_ids_and_prices(self):
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 200)
        products = {row["name"]: row for row in response.json()}
        self.assertEqual(products["Milk"]["id"], self.milk_id)
        self.assertEqual(products["Milk"]["category"], "Dairy")
        self.assertEqual(products["Milk"]["price"], "12.50")

    def test_client_cannot_supply_identity_or_prices(self):
        response = self.client.post("/orders/checkout", headers=self.headers, json={
            "customer_id": self.other_id, "total_amount": 0.01,
            "items": [{"product_id": self.milk_id, "quantity": 1, "unit_price": 0.01}],
        })
        self.assertEqual(response.status_code, 422)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 0)

    def test_empty_invalid_duplicate_unknown_and_out_of_stock_lines_are_rejected(self):
        invalid = [
            {"items": []},
            {"items": [{"product_id": self.milk_id, "quantity": 0}]},
            {"items": [{"product_id": self.milk_id, "quantity": -1}]},
            {"items": [{"product_id": self.milk_id, "quantity": 1}, {"product_id": self.milk_id, "quantity": 1}]},
        ]
        for payload in invalid:
            self.assertEqual(self.client.post("/orders/checkout", headers=self.headers, json=payload).status_code, 422)
        missing = self.client.post("/orders/checkout", headers=self.headers, json={"items": [{"product_id": 98765, "quantity": 1}]})
        unavailable = self.client.post("/orders/checkout", headers=self.headers, json={"items": [{"product_id": self.bread_id, "quantity": 3}]})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(unavailable.status_code, 409)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 0)
            self.assertEqual(db.query(OrderItem).count(), 0)

    def test_failed_order_item_insert_rolls_back_the_whole_order(self):
        with Session(self.engine) as db:
            db.execute(text(
                "CREATE TRIGGER reject_item BEFORE INSERT ON order_items "
                f"WHEN NEW.product_id = {self.bread_id} "
                "BEGIN SELECT RAISE(ABORT, 'test rollback'); END"
            ))
            db.commit()
        with self.assertLogs("api.main", level="ERROR"):
            response = self.client.post("/orders/checkout", headers=self.headers, json={"items": [
                {"product_id": self.milk_id, "quantity": 1},
                {"product_id": self.bread_id, "quantity": 1},
            ]})
        self.assertEqual(response.status_code, 500)
        with Session(self.engine) as db:
            self.assertEqual(db.query(Order).count(), 0)
            self.assertEqual(db.query(OrderItem).count(), 0)

    def test_order_history_is_scoped_to_token_customer(self):
        own = self.client.post("/orders/checkout", headers=self.headers, json={"items": [{"product_id": self.milk_id, "quantity": 1}]})
        other = self.client.post("/orders/checkout", headers=self.other_headers, json={"items": [{"product_id": self.bread_id, "quantity": 1}]})
        self.assertEqual(own.status_code, 201)
        self.assertEqual(other.status_code, 201)
        own_history = self.client.get("/orders", headers=self.headers).json()
        other_history = self.client.get("/orders", headers=self.other_headers).json()
        self.assertEqual([row["id"] for row in own_history], [own.json()["id"]])
        self.assertEqual([row["id"] for row in other_history], [other.json()["id"]])

    def test_catalogue_seed_is_repeatable_and_preserves_existing_products(self):
        first = seed_store_products(self.engine)
        second = seed_store_products(self.engine)
        self.assertEqual(first, (len(DEMO_PRODUCTS), 0))
        self.assertEqual(second, (0, len(DEMO_PRODUCTS)))
        with Session(self.engine) as db:
            self.assertEqual(db.query(Product).count(), len(DEMO_PRODUCTS) + 2)
            milk = db.scalar(select(Product).where(Product.name == "Milk"))
            self.assertEqual(milk.stock, 10)

    def test_store_seed_matches_the_frontend_catalogue_names_categories_and_prices(self):
        source = (Path(__file__).resolve().parents[1] / "frontend/src/data/products.ts").read_text(encoding="utf-8")
        pattern = re.compile(
            r'\{ id: "[^"]+", name: "([^"]+)", category: "([^"]+)", '
            r'packSize: "[^"]+", price: ([0-9.]+)'
        )
        frontend_rows = {
            (name, category, f"{Decimal(price):.2f}")
            for name, category, price in pattern.findall(source)
        }
        seeded_rows = {
            (name, category, f"{Decimal(price):.2f}")
            for name, category, price in DEMO_PRODUCTS
        }
        self.assertEqual(frontend_rows, seeded_rows)


if __name__ == "__main__":
    unittest.main()
