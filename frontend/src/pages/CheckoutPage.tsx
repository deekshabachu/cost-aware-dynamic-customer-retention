import { ArrowLeft, ArrowRight, CheckCircle2, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorState, LoadingState } from "../components/PageState";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { formatRupees } from "../data/products";
import { ApiError, api } from "../services/api";
import type { CustomerOrder, CustomerRetentionOffer, OrderPricing } from "../services/api";
import { toCheckoutLines } from "../context/cartState.js";

export function CheckoutPage() {
  const {
    items,
    clearCart,
    catalogue,
    catalogueLoading: loadingCatalogue,
    catalogueError,
    reloadCatalogue: loadCatalogue,
  } = useCart();
  const { accessToken, logout } = useAuth();
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [completedOrder, setCompletedOrder] = useState<CustomerOrder | null>(null);
  const [quote, setQuote] = useState<OrderPricing | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState("");
  const [quoteRetryKey, setQuoteRetryKey] = useState(0);
  const [retentionOffer, setRetentionOffer] = useState<CustomerRetentionOffer | null>(null);
  const [offerLoading, setOfferLoading] = useState(true);
  const [offerError, setOfferError] = useState("");
  const [applyRetentionOffer, setApplyRetentionOffer] = useState(false);

  const intervention = retentionOffer?.intervention;
  const eligibleOffer = retentionOffer?.assigned && intervention?.claimed && !intervention.expired && !intervention.redeemed
    ? intervention
    : null;

  const catalogueIds = useMemo(
    () => new Set(catalogue.map((product) => product.backendId)),
    [catalogue],
  );
  const missingProducts = items.filter(
    ({ product }) => product.backendId === undefined || !catalogueIds.has(product.backendId),
  );
  const checkoutLines = useMemo(
    () => missingProducts.length > 0 ? [] : toCheckoutLines(items),
    [items, missingProducts.length],
  );

  useEffect(() => {
    if (!accessToken) {
      setOfferLoading(false);
      setRetentionOffer(null);
      setApplyRetentionOffer(false);
      return;
    }
    let current = true;
    setOfferLoading(true);
    setOfferError("");
    api.customerRetentionOffer(accessToken)
      .then((result) => {
        if (current) {
          setRetentionOffer(result);
          setApplyRetentionOffer(false);
        }
      })
      .catch((reason: unknown) => {
        if (!current) return;
        if (reason instanceof ApiError && reason.status === 401) {
          logout();
          navigate("/login", { replace: true, state: { from: { pathname: "/checkout" }, sessionExpired: true } });
        }
        setRetentionOffer(null);
        setOfferError("We couldn't check your offer. You can continue without applying one.");
      })
      .finally(() => { if (current) setOfferLoading(false); });
    return () => { current = false; };
  }, [accessToken, logout, navigate]);

  useEffect(() => {
    if (!accessToken || checkoutLines.length === 0) {
      setQuote(null);
      setQuoteError("");
      setQuoteLoading(false);
      return;
    }
    let current = true;
    setQuote(null);
    setQuoteLoading(true);
    setQuoteError("");
    api.orderQuote(accessToken, checkoutLines, applyRetentionOffer)
      .then((result) => { if (current) setQuote(result); })
      .catch((reason: unknown) => {
        if (!current) return;
        if (reason instanceof ApiError && reason.status === 401) {
          logout();
          navigate("/login", { replace: true, state: { from: { pathname: "/checkout" }, sessionExpired: true } });
        }
        setQuote(null);
        setQuoteError(reason instanceof Error ? reason.message : "We couldn't calculate your order total. Please try again.");
      })
      .finally(() => { if (current) setQuoteLoading(false); });
    return () => { current = false; };
  }, [accessToken, applyRetentionOffer, checkoutLines, logout, navigate, quoteRetryKey]);

  const submitCheckout = async () => {
    if (!accessToken || items.length === 0 || missingProducts.length > 0 || !quote || isSubmitting) return;
    setSubmitError("");
    setIsSubmitting(true);
    try {
      const order = await api.checkout(accessToken, checkoutLines, applyRetentionOffer);
      setCompletedOrder(order);
      clearCart();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        logout();
        setSubmitError("Your sign-in expired. Please sign in again to complete checkout.");
        navigate("/login", { replace: true, state: { from: { pathname: "/checkout" }, sessionExpired: true } });
      } else {
        setSubmitError(reason instanceof Error ? reason.message : "Checkout could not be completed.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (completedOrder) {
    const completedPricing = completedOrder.pricing;
    return (
      <section className="page-shell checkout-page">
        <div className="order-confirmation">
          <CheckCircle2 size={34} />
          <span className="eyebrow">Order recorded</span>
          <h1>Thank you. Your order is saved.</h1>
          <p>Order #{completedOrder.id} · {completedOrder.status}</p>
          <p>{new Date(completedOrder.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</p>
          <div className="checkout-summary confirmation-summary">
            {completedOrder.items.map((item) => (
              <div className="checkout-item" key={item.product_id}>
                <span className="checkout-item-name">{item.product_name} <small>× {item.quantity}</small></span>
                <strong>{formatRupees(Number(item.line_total))}</strong>
              </div>
            ))}
            {completedPricing && <>
              <div className="checkout-item"><span>Subtotal</span><strong>{formatRupees(Number(completedPricing.subtotal_amount))}</strong></div>
              {Number(completedPricing.discount_amount) > 0 && <div className="checkout-item offer-price-line"><span>{completedPricing.applied_offer_name} discount</span><strong>−{formatRupees(Number(completedPricing.discount_amount))}</strong></div>}
              {completedPricing.applied_offer_name && <p className="summary-footnote">{completedPricing.applied_offer_name} applied: {completedPricing.applied_offer_description}</p>}
              <div className="checkout-item"><span>Shipping fee</span><strong>{Number(completedPricing.shipping_fee) === 0 ? "Free" : formatRupees(Number(completedPricing.shipping_fee))}</strong></div>
              {Number(completedPricing.shipping_discount_amount) > 0 && <div className="checkout-item offer-price-line"><span>Free shipping offer</span><strong>−{formatRupees(Number(completedPricing.shipping_discount_amount))}</strong></div>}
              {Number(completedPricing.shipping_discount_amount) > 0 && <div className="checkout-item"><span>Shipping payable</span><strong>{formatRupees(Number(completedPricing.shipping_fee) - Number(completedPricing.shipping_discount_amount))}</strong></div>}
              <div className="checkout-item"><span>Demo tax estimate ({completedPricing.tax_rate_percent}%)</span><strong>{formatRupees(Number(completedPricing.tax_amount))}</strong></div>
            </>}
            <div className="summary-total"><span>Total payable</span><strong>{formatRupees(Number(completedOrder.total_amount))}</strong></div>
          </div>
          <Link className="button button-dark" to="/orders">View order history <ArrowRight size={16} /></Link>
        </div>
      </section>
    );
  }

  if (!items.length) {
    return <section className="page-shell empty-page"><span className="eyebrow">Checkout</span><h1>Your bag is empty.</h1><p>Add items before checking out.</p><Link className="button button-dark" to="/">Browse the collection</Link></section>;
  }

  return (
    <section className="page-shell checkout-page">
      <Link to="/cart" className="back-link"><ArrowLeft size={16} /> Back to bag</Link>
      <div className="page-title-row"><div><span className="eyebrow">Checkout</span><h1>Review your order.</h1></div></div>
      <div className="checkout-layout">
        <div className="checkout-form">
          <section className="checkout-section"><div className="checkout-section-title"><div><h2>Customer account</h2><p>Your order will be saved to your account.</p></div></div><div className="payment-placeholder"><ShieldCheck size={19} /><span>Signed in as a LittleLeaf customer.</span></div></section>
          <section className="checkout-section"><div className="checkout-section-title"><div><h2>Payment</h2></div></div><p className="payment-disclosure">Demo checkout — no real payment will be processed.</p></section>
          <section className="checkout-section checkout-offer-section">
            <div className="checkout-section-title"><div><h2>Your retention offer</h2></div></div>
            {offerLoading && <LoadingState label="Checking your offer" />}
            {!offerLoading && offerError && <p className="form-feedback" role="status">{offerError}</p>}
            {!offerLoading && !offerError && eligibleOffer && <>
              <div className="checkout-offer-details">
                <strong>{eligibleOffer.offer.name}</strong>
                <p>{eligibleOffer.offer.description}</p>
              </div>
              <label className="checkout-offer-toggle">
                <input
                  type="checkbox"
                  checked={applyRetentionOffer}
                  onChange={(event) => setApplyRetentionOffer(event.target.checked)}
                  disabled={isSubmitting}
                />
                Apply my retention offer
              </label>
              {applyRetentionOffer && <button className="inline-link-button" type="button" onClick={() => setApplyRetentionOffer(false)} disabled={isSubmitting}>Remove offer</button>}
            </>}
            {!offerLoading && !offerError && !eligibleOffer && <p className="summary-footnote">No claimed offer is available to apply to this order.</p>}
          </section>
          {loadingCatalogue && <LoadingState label="Checking the store catalogue" />}
          {!loadingCatalogue && catalogueError && <ErrorState message={catalogueError} retry={loadCatalogue} />}
          {!loadingCatalogue && !catalogueError && catalogue.length === 0 && <p className="form-feedback form-error" role="alert">The product catalogue is empty. Products must be available before checkout.</p>}
          {!loadingCatalogue && !catalogueError && missingProducts.length > 0 && <p className="form-feedback form-error" role="alert">Some items are no longer available: {missingProducts.map(({ product }) => product.name).join(", ")}.</p>}
          {quoteError && <p className="form-feedback form-error" role="alert">{quoteError} <button className="inline-link-button" type="button" onClick={() => setQuoteRetryKey((value) => value + 1)}>Try again</button></p>}
          {submitError && <p className="form-feedback form-error" role="alert">{submitError}</p>}
          <button className="button button-dark form-submit" type="button" onClick={submitCheckout} disabled={isSubmitting || offerLoading || quoteLoading || !quote || loadingCatalogue || Boolean(catalogueError) || catalogue.length === 0 || missingProducts.length > 0}>
            {isSubmitting ? "Saving order…" : "Place order"} <ArrowRight size={16} />
          </button>
        </div>
        <aside className="checkout-summary"><span className="eyebrow">In your bag</span>
          {items.map(({ product, quantity }) => <div className="checkout-item" key={product.id}><span className="checkout-item-name">{product.name} <small>× {quantity}</small></span><strong>{formatRupees(product.price * quantity)}</strong></div>)}
          {quoteLoading && <LoadingState label="Calculating your order total" />}
          {quote && <>
            <div className="checkout-item"><span>Subtotal</span><strong>{formatRupees(Number(quote.subtotal_amount))}</strong></div>
            {Number(quote.discount_amount) > 0 && <div className="checkout-item offer-price-line"><span>{quote.applied_offer_name} discount</span><strong>−{formatRupees(Number(quote.discount_amount))}</strong></div>}
            {quote.applied_offer_name && <p className="summary-footnote">{quote.applied_offer_name} applied: {quote.applied_offer_description}</p>}
            <div className="checkout-item"><span>Shipping fee</span><strong>{Number(quote.shipping_fee) === 0 ? "Free" : formatRupees(Number(quote.shipping_fee))}</strong></div>
            {Number(quote.shipping_discount_amount) > 0 && <div className="checkout-item offer-price-line"><span>Free shipping offer</span><strong>−{formatRupees(Number(quote.shipping_discount_amount))}</strong></div>}
            {Number(quote.shipping_discount_amount) > 0 && <div className="checkout-item"><span>Shipping payable</span><strong>{formatRupees(Number(quote.shipping_fee) - Number(quote.shipping_discount_amount))}</strong></div>}
            <div className="checkout-item"><span>Demo tax estimate ({quote.tax_rate_percent}%)</span><strong>{formatRupees(Number(quote.tax_amount))}</strong></div>
            <div className="summary-total"><span>Total payable</span><strong>{formatRupees(Number(quote.total_amount))}</strong></div>
            <p className="summary-footnote">Tax is a configurable demo estimate on the product subtotal after any offer discount, not a GST invoice.</p>
          </>}
        </aside>
      </div>
    </section>
  );
}
