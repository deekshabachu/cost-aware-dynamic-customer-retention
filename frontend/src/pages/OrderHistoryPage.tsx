import { ArrowRight, PackageCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorState, LoadingState } from "../components/PageState";
import { useAuth } from "../context/AuthContext";
import { formatRupees } from "../data/products";
import { ApiError, api } from "../services/api";
import type { CustomerOrder } from "../services/api";

export function OrderHistoryPage() {
  const { accessToken, logout } = useAuth();
  const navigate = useNavigate();
  const [orders, setOrders] = useState<CustomerOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadOrders = useCallback(() => {
    if (!accessToken) return;
    setLoading(true);
    setError("");
    api.orderHistory(accessToken)
      .then(setOrders)
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 401) {
          logout();
          navigate("/login", { replace: true, state: { from: { pathname: "/orders" }, sessionExpired: true } });
        } else {
          setError(reason instanceof Error ? reason.message : "Order history could not be loaded.");
        }
      })
      .finally(() => setLoading(false));
  }, [accessToken, logout, navigate]);

  useEffect(() => { loadOrders(); }, [loadOrders]);

  return (
    <section className="page-shell orders-page">
      <div className="page-title-row"><div><span className="eyebrow">Order history</span><h1>Your orders.</h1></div></div>
      {loading && <LoadingState label="Loading your saved orders" />}
      {!loading && error && <ErrorState message={error} retry={loadOrders} />}
      {!loading && !error && orders.length === 0 && (
        <div className="orders-placeholder">
          <div className="empty-icon"><PackageCheck size={23} /></div>
          <span className="eyebrow">Order history</span>
          <h2>Nothing to look back on just yet.</h2>
          <p>Your orders will appear here after checkout.</p>
          <Link className="button button-outline" to="/">Explore the collection <ArrowRight size={15} /></Link>
        </div>
      )}
      {!loading && !error && orders.length > 0 && <div className="order-history-list">
        {orders.map((order) => (
          <article className="saved-order-card" key={order.id}>
            <div className="saved-order-heading">
              <div><span className="eyebrow">Order #{order.id}</span><h2>{new Date(order.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</h2></div>
              <span className="order-status">{order.status.replaceAll("_", " ")}</span>
            </div>
            <div className="saved-order-items">
              {order.items.length === 0 && <p className="summary-footnote">This order has no saved item breakdown.</p>}
              {order.items.map((item) => (
                <div className="checkout-item" key={item.product_id}>
                  <span className="checkout-item-name">{item.product_name} <small>× {item.quantity}</small></span>
                  <strong>{formatRupees(Number(item.line_total))}</strong>
                </div>
              ))}
            </div>
            {order.pricing && <div className="saved-order-pricing">
              <div className="checkout-item"><span>Subtotal</span><strong>{formatRupees(Number(order.pricing.subtotal_amount))}</strong></div>
              {Number(order.pricing.discount_amount) > 0 && <div className="checkout-item offer-price-line"><span>{order.pricing.applied_offer_name} discount</span><strong>−{formatRupees(Number(order.pricing.discount_amount))}</strong></div>}
              {order.pricing.applied_offer_name && <p className="summary-footnote">{order.pricing.applied_offer_name} applied: {order.pricing.applied_offer_description}</p>}
              <div className="checkout-item"><span>Shipping fee</span><strong>{Number(order.pricing.shipping_fee) === 0 ? "Free" : formatRupees(Number(order.pricing.shipping_fee))}</strong></div>
              {Number(order.pricing.shipping_discount_amount) > 0 && <div className="checkout-item offer-price-line"><span>Free shipping offer</span><strong>−{formatRupees(Number(order.pricing.shipping_discount_amount))}</strong></div>}
              {Number(order.pricing.shipping_discount_amount) > 0 && <div className="checkout-item"><span>Shipping payable</span><strong>{formatRupees(Number(order.pricing.shipping_fee) - Number(order.pricing.shipping_discount_amount))}</strong></div>}
              <div className="checkout-item"><span>Demo tax estimate ({order.pricing.tax_rate_percent}%)</span><strong>{formatRupees(Number(order.pricing.tax_amount))}</strong></div>
            </div>}
            <div className="summary-total"><span>Total</span><strong>{formatRupees(Number(order.total_amount))}</strong></div>
          </article>
        ))}
      </div>}
    </section>
  );
}
