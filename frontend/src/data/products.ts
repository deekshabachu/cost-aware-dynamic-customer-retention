import type { StoreProduct } from "../services/api";

export type Product = {
  id: string;
  /** Database product ID used by checkout; optional only for the static legacy map. */
  backendId?: number;
  name: string;
  category: string;
  packSize: string;
  price: number;
  description: string;
  emoji: string;
  tone: string;
  badge?: string;
};

export const categories = [
  "All", "Groceries & Dairy", "Snacks", "Beverages",
  "Fruits & Vegetables", "Home Care", "Personal Care",
] as const;

// Presentation-only demo catalogue; these products are not sourced from the churn dataset.
export const products: Product[] = [
  { id: "milk", name: "Amul Taaza Toned Milk", category: "Groceries & Dairy", packSize: "500 ml", price: 29, description: "Everyday toned milk for tea, coffee and breakfast.", emoji: "🥛", tone: "oat", badge: "Popular" },
  { id: "curd", name: "Mother Dairy Classic Curd", category: "Groceries & Dairy", packSize: "400 g", price: 38, description: "Creamy set curd for meals, raita and snacks.", emoji: "🥣", tone: "butter" },
  { id: "paneer", name: "Amul Fresh Paneer", category: "Groceries & Dairy", packSize: "200 g", price: 92, description: "Soft paneer cubes for curries, rolls and quick dinners.", emoji: "🧀", tone: "peach" },
  { id: "butter", name: "Amul Butter", category: "Groceries & Dairy", packSize: "100 g", price: 58, description: "Classic salted butter for toast and home cooking.", emoji: "🧈", tone: "butter" },
  { id: "bread", name: "Harvest Gold White Bread", category: "Groceries & Dairy", packSize: "400 g", price: 40, description: "Soft sliced bread for sandwiches and breakfast.", emoji: "🍞", tone: "clay" },
  { id: "eggs", name: "Farm Fresh Eggs", category: "Groceries & Dairy", packSize: "6 pieces", price: 54, description: "A half-dozen everyday eggs, packed for home use.", emoji: "🥚", tone: "oat" },
  { id: "chips", name: "Lay’s Classic Salted Chips", category: "Snacks", packSize: "52 g", price: 20, description: "Crispy potato chips with a simple salted flavour.", emoji: "🍟", tone: "butter" },
  { id: "biscuits", name: "Parle-G Glucose Biscuits", category: "Snacks", packSize: "250 g", price: 25, description: "A familiar tea-time biscuit for the whole family.", emoji: "🍪", tone: "clay" },
  { id: "chocolate", name: "Cadbury Dairy Milk", category: "Snacks", packSize: "110 g", price: 99, description: "A smooth milk chocolate bar for a little treat.", emoji: "🍫", tone: "lilac" },
  { id: "noodles", name: "Maggi Masala Noodles", category: "Snacks", packSize: "2 pack · 140 g", price: 28, description: "Quick-cooking masala noodles for an easy snack.", emoji: "🍜", tone: "peach" },
  { id: "water", name: "Bisleri Mineral Water", category: "Beverages", packSize: "1 litre", price: 20, description: "Packaged drinking water for everyday hydration.", emoji: "💧", tone: "blue" },
  { id: "juice", name: "Real Mixed Fruit Juice", category: "Beverages", packSize: "1 litre", price: 110, description: "A chilled fruit drink for breakfast or sharing.", emoji: "🧃", tone: "rose" },
  { id: "cola", name: "Coca-Cola Soft Drink", category: "Beverages", packSize: "750 ml", price: 40, description: "A chilled sparkling soft drink for meals and get-togethers.", emoji: "🥤", tone: "rose" },
  { id: "bananas", name: "Yelakki Bananas", category: "Fruits & Vegetables", packSize: "6 pieces", price: 45, description: "Naturally sweet bananas, selected for everyday snacking.", emoji: "🍌", tone: "butter" },
  { id: "apples", name: "Shimla Apples", category: "Fruits & Vegetables", packSize: "4 pieces · approx. 500 g", price: 99, description: "Crisp apples for lunchboxes, snacks and fruit bowls.", emoji: "🍎", tone: "rose" },
  { id: "onions", name: "Red Onions", category: "Fruits & Vegetables", packSize: "1 kg", price: 42, description: "Kitchen-ready red onions for daily cooking.", emoji: "🧅", tone: "lilac" },
  { id: "potatoes", name: "Fresh Potatoes", category: "Fruits & Vegetables", packSize: "1 kg", price: 35, description: "Versatile potatoes for curries, snacks and sides.", emoji: "🥔", tone: "clay" },
  { id: "tomatoes", name: "Farm Fresh Tomatoes", category: "Fruits & Vegetables", packSize: "500 g", price: 30, description: "Ripe tomatoes for everyday meals and salads.", emoji: "🍅", tone: "peach" },
  { id: "detergent", name: "Surf Excel Easy Wash", category: "Home Care", packSize: "1 kg", price: 112, description: "Laundry detergent powder for your regular wash.", emoji: "🧺", tone: "blue" },
  { id: "dishwash", name: "Vim Dishwash Liquid", category: "Home Care", packSize: "500 ml", price: 115, description: "Dishwashing liquid for everyday plates and cookware.", emoji: "🧽", tone: "sage" },
  { id: "tissues", name: "Origami Facial Tissues", category: "Home Care", packSize: "100 pulls", price: 75, description: "Soft facial tissues for home, desk or bedside.", emoji: "🧻", tone: "oat" },
  { id: "soap", name: "Dove Cream Beauty Bathing Bar", category: "Personal Care", packSize: "100 g", price: 62, description: "A moisturising beauty bar for your daily bath.", emoji: "🧼", tone: "blue" },
  { id: "shampoo", name: "Clinic Plus Strong & Long Shampoo", category: "Personal Care", packSize: "175 ml", price: 112, description: "Everyday shampoo in a convenient family-size bottle.", emoji: "🧴", tone: "lilac" },
  { id: "toothpaste", name: "Colgate Strong Teeth Toothpaste", category: "Personal Care", packSize: "150 g", price: 99, description: "A daily fluoride toothpaste for the whole family.", emoji: "🪥", tone: "blue" },
];

/** Use database values as the catalogue source while retaining local artwork metadata. */
export function mapStoreProduct(row: StoreProduct): Product {
  const price = Number(row.price);
  if (!Number.isFinite(price) || price < 0) {
    throw new Error(`The catalogue contains an invalid price for ${row.name}.`);
  }

  const presentation = products.find((product) => product.name === row.name);
  return {
    id: presentation?.id ?? `db-${row.id}`,
    backendId: row.id,
    name: row.name,
    category: row.category,
    packSize: presentation?.packSize ?? "Pack size not specified",
    price,
    description: presentation?.description ?? `A grocery item in ${row.category}.`,
    emoji: presentation?.emoji ?? "🛒",
    tone: presentation?.tone ?? "oat",
    badge: presentation?.badge,
  };
}

export function formatRupees(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(amount);
}
