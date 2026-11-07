import assert from "node:assert/strict";
import test from "node:test";
import {
  CART_STORAGE_KEY,
  calculateCartSubtotal,
  decrementCartQuantity,
  incrementCartQuantity,
  readCartLines,
  removeCartProduct,
  saveCartLines,
  toCheckoutLines,
  updateCartQuantity,
} from "../src/context/cartState.js";

const initial = [{ productId: "milk", quantity: 2 }, { productId: "bread", quantity: 1 }];

test("increments an existing item and adds a new item at one", () => {
  assert.deepEqual(incrementCartQuantity(initial, "milk"), [
    { productId: "milk", quantity: 3 }, { productId: "bread", quantity: 1 },
  ]);
  assert.deepEqual(incrementCartQuantity(initial, "eggs"), [
    ...initial, { productId: "eggs", quantity: 1 },
  ]);
});

test("decrements quantity and removes a line when it reaches zero", () => {
  assert.deepEqual(updateCartQuantity(initial, "milk", 1), [
    { productId: "milk", quantity: 1 }, { productId: "bread", quantity: 1 },
  ]);
  assert.deepEqual(updateCartQuantity([{ productId: "milk", quantity: 1 }], "milk", 0), []);
});

test("visible decrement action subtracts exactly one and removes at one", () => {
  assert.deepEqual(decrementCartQuantity(initial, "milk"), [
    { productId: "milk", quantity: 1 }, { productId: "bread", quantity: 1 },
  ]);
  assert.deepEqual(decrementCartQuantity([{ productId: "milk", quantity: 1 }], "milk"), []);
  assert.deepEqual(decrementCartQuantity(initial, "unknown"), initial);
});

test("rejects non-integer and negative quantities without changing lines", () => {
  assert.equal(updateCartQuantity(initial, "milk", -1), initial);
  assert.equal(updateCartQuantity(initial, "milk", 1.5), initial);
});

test("removal and subtotal reflect the changed cart immediately", () => {
  const products = [
    { product: { id: "milk", price: 29 }, quantity: 3 },
    { product: { id: "bread", price: 40 }, quantity: 1 },
  ];
  assert.equal(calculateCartSubtotal(products), 127);
  const lowered = products.map((item) => item.product.id === "milk" ? { ...item, quantity: 2 } : item);
  assert.equal(calculateCartSubtotal(lowered), 98);
  assert.deepEqual(removeCartProduct(initial, "milk"), [{ productId: "bread", quantity: 1 }]);
});

test("cart lines persist under the existing key and invalid saved quantities are ignored", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  saveCartLines(storage, initial);
  assert.equal(CART_STORAGE_KEY, "fieldwork-demo-cart-v1");
  assert.deepEqual(readCartLines(storage, new Set(["milk", "bread"])), initial);
  values.set(CART_STORAGE_KEY, JSON.stringify([
    { productId: "milk", quantity: 0 },
    { productId: "bread", quantity: 2.5 },
    { productId: "db-12", quantity: 3 },
  ]));
  assert.deepEqual(readCartLines(storage, new Set(["milk", "bread"])), [
    { productId: "db-12", quantity: 3 },
  ]);
});

test("checkout lines preserve backend product IDs and current quantities", () => {
  assert.deepEqual(toCheckoutLines([
    { product: { id: "milk", backendId: 7, price: 29 }, quantity: 3 },
    { product: { id: "bread", backendId: 12, price: 40 }, quantity: 1 },
  ]), [{ product_id: 7, quantity: 3 }, { product_id: 12, quantity: 1 }]);
});
