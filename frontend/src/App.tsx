import { X } from "lucide-react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { SiteFooter } from "./components/SiteFooter";
import { SiteHeader } from "./components/SiteHeader";
import { useCart } from "./context/CartContext";
import { useAuth } from "./context/AuthContext";
import { LoadingState } from "./components/PageState";
import type { ReactNode } from "react";
import { LoginPage, RegisterPage } from "./pages/AccountPages";
import { CartPage } from "./pages/CartPage";
import { AdminDashboardPage } from "./pages/AdminDashboardPage";
import { CheckoutPage } from "./pages/CheckoutPage";
import { HomePage } from "./pages/HomePage";
import { OrderHistoryPage } from "./pages/OrderHistoryPage";
import { ProductDetailsPage } from "./pages/ProductDetailsPage";
import { RetentionOfferPage } from "./pages/RetentionOfferPage";

function NotFoundPage() {
  return <section className="page-shell simple-page"><span className="eyebrow">A little detour</span><h1>This page isn't on the shelf.</h1><Link className="button button-dark" to="/">Back to the collection</Link></section>;
}

function RequireCustomer({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) return <section className="page-shell simple-page"><LoadingState label="Checking your sign-in" /></section>;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return children;
}

export default function App() {
  const { notice, clearNotice } = useCart();
  return (
    <div className="app-frame">
      <SiteHeader />
      {notice && <div className="toast-message" role="status"><span>{notice}</span><button onClick={clearNotice} aria-label="Dismiss notification"><X size={16} /></button></div>}
      <main>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/products/:productId" element={<ProductDetailsPage />} />
          <Route path="/cart" element={<CartPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/admin" element={<AdminDashboardPage />} />
          <Route path="/checkout" element={<RequireCustomer><CheckoutPage /></RequireCustomer>} />
          <Route path="/orders" element={<RequireCustomer><OrderHistoryPage /></RequireCustomer>} />
          <Route path="/retention-offer" element={<RequireCustomer><RetentionOfferPage /></RequireCustomer>} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
      <SiteFooter />
    </div>
  );
}
