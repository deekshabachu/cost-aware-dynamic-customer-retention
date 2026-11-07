import { ArrowUpRight, MapPin, Menu, Search, ShoppingBag, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, NavLink, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";

export function SiteHeader() {
  const { count } = useCart();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const navigate = useNavigate();

  useEffect(() => setSearch(searchParams.get("q") ?? ""), [searchParams]);

  const closeMenu = () => setMenuOpen(false);
  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = search.trim();
    navigate(query ? `/?q=${encodeURIComponent(query)}#catalog` : "/#catalog");
    closeMenu();
  };

  return (
    <>
    <div className="topline"><MapPin size={13} /> <span className="location-label">Delivering to</span> <strong>Kokapet, Hyderabad</strong></div>
      <header className="site-header">
        <div className="header-inner page-shell">
          <Link className="brand" to="/" onClick={closeMenu} aria-label="LittleLeaf home">
            <span className="brand-mark"><span /></span>
            <span>LittleLeaf</span>
          </Link>
          <form className="header-search" role="search" onSubmit={submitSearch}>
            <Search size={18} aria-hidden="true" />
            <input aria-label="Search products" placeholder="Search for milk, fruits, snacks..." value={search} onChange={(event) => setSearch(event.target.value)} />
            {search && <button type="button" onClick={() => { setSearch(""); navigate("/#catalog"); }} aria-label="Clear search"><X size={16} /></button>}
          </form>
          <button className="mobile-menu-toggle icon-button" onClick={() => setMenuOpen((open) => !open)} aria-label={menuOpen ? "Close navigation" : "Open navigation"} aria-expanded={menuOpen}>
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <nav className={`main-nav ${menuOpen ? "is-open" : ""}`} aria-label="Main navigation">
            <NavLink to="/" onClick={closeMenu}>Shop</NavLink>
            <NavLink to="/retention-offer" onClick={closeMenu}>Your offer</NavLink>
            <NavLink to="/orders" onClick={closeMenu}>Orders</NavLink>
            {user ? <NavLink className="mobile-account-nav" to="/orders" onClick={closeMenu}>{user.email}</NavLink> : <NavLink className="mobile-account-nav" to="/login" onClick={closeMenu}>Account / Sign in</NavLink>}
            {user && <button className="mobile-logout" type="button" onClick={() => { logout(); closeMenu(); }}>Sign out</button>}
          </nav>
          <div className="header-actions">
            {user ? <><Link className="account-link signed-in-email" to="/orders" title={user.email}>{user.email}</Link><button className="logout-link" type="button" onClick={logout}>Sign out</button></> : <Link className="account-link" to="/login">Account <ArrowUpRight size={14} /></Link>}
            <Link className="cart-link" to="/cart" aria-label={`Shopping bag, ${count} items`}>
              <ShoppingBag size={19} strokeWidth={1.7} />
              <span>Bag</span>
              <span className="cart-count">{count}</span>
            </Link>
          </div>
        </div>
      </header>
    </>
  );
}
