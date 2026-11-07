/** @typedef {{ productId: string, quantity: number }} CartLine */

export const CART_STORAGE_KEY = "fieldwork-demo-cart-v1";

/** @param {CartLine[]} lines @param {string} productId */
export function incrementCartQuantity(lines, productId) {
  const existing = lines.find((line) => line.productId === productId);
  return existing
    ? lines.map((line) => line.productId === productId
      ? { ...line, quantity: line.quantity + 1 }
      : line)
    : [...lines, { productId, quantity: 1 }];
}

/** A quantity of zero removes the line; invalid or negative values are ignored. */
/** @param {CartLine[]} lines @param {string} productId @param {number} quantity */
export function updateCartQuantity(lines, productId, quantity) {
  if (!Number.isSafeInteger(quantity) || quantity < 0) return lines;
  if (quantity === 0) return lines.filter((line) => line.productId !== productId);
  return lines.map((line) => line.productId === productId ? { ...line, quantity } : line);
}

/** Reduce a product quantity by one; a quantity of one removes its cart line. */
/** @param {CartLine[]} lines @param {string} productId */
export function decrementCartQuantity(lines, productId) {
  const current = lines.find((line) => line.productId === productId);
  if (!current) return lines;
  return updateCartQuantity(lines, productId, current.quantity - 1);
}

/** @param {CartLine[]} lines @param {string} productId */
export function removeCartProduct(lines, productId) {
  return lines.filter((line) => line.productId !== productId);
}

/** @param {{ product: { id: string, price: number }, quantity: number }[]} items */
export function calculateCartSubtotal(items) {
  return items.reduce((sum, item) => sum + item.product.price * item.quantity, 0);
}

/** @param {{ getItem(key: string): string | null }} storage @param {Set<string>} knownProductIds @returns {CartLine[]} */
export function readCartLines(storage, knownProductIds) {
  try {
    const saved = storage.getItem(CART_STORAGE_KEY);
    if (!saved) return [];
    const parsed = JSON.parse(saved);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((line) =>
      line !== null && typeof line === "object" &&
      typeof line.productId === "string" &&
      Number.isSafeInteger(line.quantity) && line.quantity > 0 &&
      (knownProductIds.has(line.productId) || /^db-\d+$/.test(line.productId))
    );
  } catch {
    return [];
  }
}

/** @param {{ setItem(key: string, value: string): void }} storage @param {CartLine[]} lines */
export function saveCartLines(storage, lines) {
  storage.setItem(CART_STORAGE_KEY, JSON.stringify(lines));
}

/** @param {{ backendId?: number, id: string, price: number }[]} items */
export function toCheckoutLines(items) {
  return items.map(({ product, quantity }) => {
    if (product.backendId === undefined) {
      throw new Error(`${product.id} is not available in the database catalogue.`);
    }
    if (!Number.isSafeInteger(quantity) || quantity < 1) {
      throw new Error(`Cart quantity for ${product.id} must be a positive integer.`);
    }
    return { product_id: product.backendId, quantity };
  });
}
