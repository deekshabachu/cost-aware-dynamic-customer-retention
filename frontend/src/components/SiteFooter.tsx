import { Link } from "react-router-dom";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="page-shell footer-main">
        <div>
          <Link className="brand footer-brand" to="/">
            <span className="brand-mark"><span /></span>
            <span>LittleLeaf</span>
          </Link>
          <p>Everyday essentials for your home.</p>
        </div>
        <div className="footer-links">
          <span className="eyebrow">Explore</span>
          <Link to="/">Shop essentials</Link>
          <Link to="/retention-offer">Your offer</Link>
          <Link to="/orders">Order history</Link>
        </div>
      </div>
      <div className="page-shell footer-bottom"><span>© 2026 LittleLeaf</span><span>Made for everyday living</span></div>
    </footer>
  );
}
