import { ArrowRight, Minus, Plus, ShoppingBag, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorState, LoadingState } from "../components/PageState";
import { ProductArtwork } from "../components/ProductArtwork";
import { formatRupees } from "../data/products";
import { useCart } from "../context/CartContext";

export function CartPage() {
  const {
    items,
    subtotal,
    setQuantity,
    removeProduct,
    catalogueLoading,
    catalogueError,
    reloadCatalogue,
  } = useCart();
  if (catalogueLoading) return <section className="page-shell simple-page"><LoadingState label="Loading your cart products" /></section>;
  if (catalogueError) return <section className="page-shell simple-page"><ErrorState message={catalogueError} retry={reloadCatalogue} /></section>;
  if (items.length === 0) {
    return (
      <section className="page-shell empty-page">
        <div className="empty-icon"><ShoppingBag size={24} /></div>
        <span className="eyebrow">Your shopping bag</span>
        <h1>Your bag is empty.</h1>
        <p>Browse everyday essentials and add a few items to your bag.</p>
        <Link className="button button-dark" to="/">Browse essentials <ArrowRight size={16} /></Link>
      </section>
    );
  }

  return (
    <section className="page-shell cart-page">
      <div className="page-title-row"><div><span className="eyebrow">Your shopping bag</span><h1>Your bag.</h1></div><span className="muted">{items.reduce((sum, item) => sum + item.quantity, 0)} items</span></div>
      <p className="cart-storage-note">Your cart is saved in this browser.</p>
      <div className="cart-layout">
        <div className="cart-items">
          {items.map(({ product, quantity }) => (
            <article className="cart-row" key={product.id}>
              <Link to={`/products/${product.id}`} className="cart-thumb"><ProductArtwork product={product} compact /></Link>
              <div className="cart-row-main"><span className="product-category">{product.category}</span><Link to={`/products/${product.id}`} className="product-name">{product.name}</Link><span className="cart-unit-price">{formatRupees(product.price)} each</span></div>
              <div className="quantity-control" aria-label={`Quantity for ${product.name}`}>
                <button type="button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); setQuantity(product.id, quantity - 1); }} aria-label={`Decrease ${product.name} quantity`}><Minus size={14} /></button>
                <span>{quantity}</span>
                <button type="button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); setQuantity(product.id, quantity + 1); }} aria-label={`Increase ${product.name} quantity`}><Plus size={14} /></button>
              </div>
              <strong className="cart-line-total">{formatRupees(product.price * quantity)}</strong>
              <button className="remove-button" type="button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); removeProduct(product.id); }} aria-label={`Remove ${product.name}`}><Trash2 size={17} /></button>
            </article>
          ))}
        </div>
        <aside className="order-summary">
          <span className="eyebrow">A little summary</span>
          <div className="summary-total"><span>Subtotal</span><strong>{formatRupees(subtotal)}</strong></div>
          <Link className="button button-dark checkout-link" to="/checkout">Continue to checkout <ArrowRight size={16} /></Link>
        </aside>
      </div>
    </section>
  );
}
