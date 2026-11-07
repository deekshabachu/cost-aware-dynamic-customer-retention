"""Explicitly seed the LittleLeaf demo catalogue into the products table.

Run manually with ``python -m scripts.seed_store_products``. Existing rows are
reused by exact name and are never overwritten. The demo stock values are
illustrative availability values; checkout does not decrement stock.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.config import create_database_engine
from database.initialize import initialize_database
from database.models import Product


DEMO_PRODUCTS = (
    ("Amul Taaza Toned Milk", "Groceries & Dairy", "29.00"),
    ("Mother Dairy Classic Curd", "Groceries & Dairy", "38.00"),
    ("Amul Fresh Paneer", "Groceries & Dairy", "92.00"),
    ("Amul Butter", "Groceries & Dairy", "58.00"),
    ("Harvest Gold White Bread", "Groceries & Dairy", "40.00"),
    ("Farm Fresh Eggs", "Groceries & Dairy", "54.00"),
    ("Lay’s Classic Salted Chips", "Snacks", "20.00"),
    ("Parle-G Glucose Biscuits", "Snacks", "25.00"),
    ("Cadbury Dairy Milk", "Snacks", "99.00"),
    ("Maggi Masala Noodles", "Snacks", "28.00"),
    ("Bisleri Mineral Water", "Beverages", "20.00"),
    ("Real Mixed Fruit Juice", "Beverages", "110.00"),
    ("Coca-Cola Soft Drink", "Beverages", "40.00"),
    ("Yelakki Bananas", "Fruits & Vegetables", "45.00"),
    ("Shimla Apples", "Fruits & Vegetables", "99.00"),
    ("Red Onions", "Fruits & Vegetables", "42.00"),
    ("Fresh Potatoes", "Fruits & Vegetables", "35.00"),
    ("Farm Fresh Tomatoes", "Fruits & Vegetables", "30.00"),
    ("Surf Excel Easy Wash", "Home Care", "112.00"),
    ("Vim Dishwash Liquid", "Home Care", "115.00"),
    ("Origami Facial Tissues", "Home Care", "75.00"),
    ("Dove Cream Beauty Bathing Bar", "Personal Care", "62.00"),
    ("Clinic Plus Strong & Long Shampoo", "Personal Care", "112.00"),
    ("Colgate Strong Teeth Toothpaste", "Personal Care", "99.00"),
)


def seed_store_products(database_engine=None) -> tuple[int, int]:
    """Insert missing demo catalogue rows, preserving all existing records."""
    engine = database_engine or create_database_engine()
    initialize_database(engine)
    created = 0
    reused = 0
    with Session(engine) as session, session.begin():
        for name, category, price_text in DEMO_PRODUCTS:
            price = Decimal(price_text)
            existing = session.scalar(select(Product).where(Product.name == name))
            if existing is not None:
                if existing.category != category or Decimal(existing.price) != price:
                    raise ValueError(
                        f"Existing product {name!r} differs from the demo catalogue; "
                        "no existing fields were changed."
                    )
                reused += 1
                continue
            session.add(
                Product(
                    name=name,
                    category=category,
                    description="LittleLeaf demo catalogue item.",
                    price=price,
                    stock=100,
                )
            )
            created += 1
    return created, reused


def main() -> None:
    engine = create_database_engine()
    try:
        created, reused = seed_store_products(engine)
        print(f"Store catalogue seeded: {created} created, {reused} reused.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
