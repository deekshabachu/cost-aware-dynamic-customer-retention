import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../services/api";
import { mapStoreProduct, products } from "../data/products";
import type { Product } from "../data/products";
import {
  calculateCartSubtotal,
  decrementCartQuantity,
  incrementCartQuantity,
  readCartLines,
  removeCartProduct,
  saveCartLines,
  updateCartQuantity,
} from "./cartState.js";
import type { CartLine } from "./cartState.js";

export type CartItem = { product: Product; quantity: number };

type CartContextValue = {
  items: CartItem[];
  count: number;
  subtotal: number;
  notice: string;
  addProduct: (product: Product) => void;
  setQuantity: (productId: string, quantity: number) => void;
  decrementProduct: (productId: string) => void;
  removeProduct: (productId: string) => void;
  clearCart: () => void;
  clearNotice: () => void;
  catalogue: Product[];
  catalogueLoading: boolean;
  catalogueError: string;
  reloadCatalogue: () => void;
};

const CartContext = createContext<CartContextValue | null>(null);

export function CartProvider({ children }: { children: ReactNode }) {
  const [lines, setLines] = useState<CartLine[]>(() =>
    readCartLines(window.localStorage, new Set(products.map((product) => product.id))),
  );
  const [notice, setNotice] = useState("");
  const [catalogue, setCatalogue] = useState<Product[]>([]);
  const [catalogueLoading, setCatalogueLoading] = useState(true);
  const [catalogueError, setCatalogueError] = useState("");

  const reloadCatalogue = useCallback(() => {
    setCatalogueLoading(true);
    setCatalogueError("");
    api.products()
      .then((rows) => setCatalogue(rows.map(mapStoreProduct)))
      .catch((reason: unknown) => {
        setCatalogue([]);
        setCatalogueError(
          reason instanceof Error ? reason.message : "The store catalogue could not be loaded.",
        );
      })
      .finally(() => setCatalogueLoading(false));
  }, []);

  useEffect(() => { reloadCatalogue(); }, [reloadCatalogue]);

  useEffect(() => {
    saveCartLines(window.localStorage, lines);
  }, [lines]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 2800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const value = useMemo<CartContextValue>(() => {
    const items = lines.flatMap((line) => {
      const product = catalogue.find((item) => item.id === line.productId);
      return product ? [{ product, quantity: line.quantity }] : [];
    });
    return {
      items,
      count: items.reduce((sum, item) => sum + item.quantity, 0),
      subtotal: calculateCartSubtotal(items),
      notice,
      catalogue,
      catalogueLoading,
      catalogueError,
      reloadCatalogue,
      addProduct: (product) => {
        setLines((current) => incrementCartQuantity(current, product.id));
        setNotice(`${product.name} added to your cart.`);
      },
      setQuantity: (productId, quantity) => {
        setLines((current) => updateCartQuantity(current, productId, quantity));
      },
      decrementProduct: (productId) => {
        setLines((current) => decrementCartQuantity(current, productId));
      },
      removeProduct: (productId) =>
        setLines((current) => removeCartProduct(current, productId)),
      clearCart: () => setLines([]),
      clearNotice: () => setNotice(""),
    };
  }, [lines, notice, catalogue, catalogueLoading, catalogueError, reloadCatalogue]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartContextValue {
  const context = useContext(CartContext);
  if (!context) throw new Error("useCart must be used inside CartProvider.");
  return context;
}
