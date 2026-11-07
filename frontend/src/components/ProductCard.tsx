import { Minus, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { formatRupees } from "../data/products";
import type { Product } from "../data/products";
import { useCart } from "../context/CartContext";
import { ProductArtwork } from "./ProductArtwork";

export function ProductCard({ product }: { product: Product }) {
  const { addProduct, decrementProduct, items } = useCart();
  const quantity = items.find((item) => item.product.id === product.id)?.quantity ?? 0;
  return (
    <article className="product-card grocery-card">
      <Link className="product-art-link" to={`/products/${product.id}`} aria-label={`View ${product.name}`}>
        <ProductArtwork product={product} />
        {product.badge && <span className="product-badge">{product.badge}</span>}
      </Link>
      <div className="product-card-info">
        <div className="grocery-product-copy">
          <span className="product-pack-size">{product.packSize}</span>
          <Link to={`/products/${product.id}`} className="product-name" title={product.name}>{product.name}</Link>
          <span className="product-price">{formatRupees(product.price)}</span>
        </div>
        {quantity > 0 ? (
          <div className="card-quantity-control" aria-label={`Quantity for ${product.name}`}>
            <button type="button" onClick={() => decrementProduct(product.id)} aria-label={`Decrease ${product.name} quantity`}>
              <Minus size={14} />
            </button>
            <span aria-live="polite">{quantity}</span>
            <button type="button" onClick={() => addProduct(product)} aria-label={`Increase ${product.name} quantity`}>
              <Plus size={14} />
            </button>
          </div>
        ) : (
          <button className="quick-add grocery-add" type="button" onClick={() => addProduct(product)} aria-label={`Add ${product.name} to cart`}>
            <Plus size={14} /> ADD
          </button>
        )}
      </div>
    </article>
  );
}
