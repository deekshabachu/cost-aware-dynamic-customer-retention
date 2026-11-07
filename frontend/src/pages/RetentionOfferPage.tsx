import { ArrowUpRight, Gift, HeartHandshake } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ErrorState, LoadingState } from "../components/PageState";
import { useAuth } from "../context/AuthContext";
import { api, ApiError } from "../services/api";
import type { CustomerRetentionOffer } from "../services/api";
import { getRetentionOfferStatus } from "./retentionOfferStatus.js";

export function RetentionOfferPage() {
  const { accessToken, logout } = useAuth();
  const navigate = useNavigate();
  const [result, setResult] = useState<CustomerRetentionOffer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [claiming, setClaiming] = useState(false);
  const [claimError, setClaimError] = useState("");
  const offerStatus = getRetentionOfferStatus(
    loading,
    Boolean(error),
    result?.assigned,
    result?.intervention?.claimed,
    result?.intervention?.expired,
    result?.intervention?.redeemed,
  );

  const loadAssignedOffer = useCallback(() => {
    if (!accessToken) {
      setError("Please sign in to view your assigned offer.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    api.customerRetentionOffer(accessToken)
      .then(setResult)
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 401) {
          logout();
          navigate("/login", { replace: true, state: { from: { pathname: "/retention-offer" } } });
        }
        setError(reason instanceof Error ? reason.message : "Your assigned offer is currently unavailable.");
      })
      .finally(() => setLoading(false));
  }, [accessToken, logout, navigate]);

  async function claimOffer() {
    if (!accessToken || !result?.assigned || result.intervention?.claimed || claiming) return;
    setClaimError("");
    setClaiming(true);
    try {
      await api.claimRetentionOffer(accessToken);
      await loadAssignedOffer();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        logout();
        navigate("/login", { replace: true, state: { from: { pathname: "/retention-offer" } } });
      }
      setClaimError(reason instanceof Error ? reason.message : "The offer could not be claimed.");
    } finally {
      setClaiming(false);
    }
  }

  useEffect(() => { loadAssignedOffer(); }, [loadAssignedOffer]);

  return (
    <section className="page-shell offer-page">
      <div className="offer-hero">
        <div className="offer-hero-icon"><HeartHandshake size={25} strokeWidth={1.6} /></div>
        <span className="eyebrow">A note, just for you</span>
        <h1>Your LittleLeaf<br /><em>offer.</em></h1>
        <p>Any offer shown here is assigned specifically to your account.</p>
      </div>
      <div className="assigned-offer-card">
        <div className="offer-status-row">
          <span className="eyebrow">Your personal offer</span>
          {offerStatus && (
            <span className={`offer-status-badge ${offerStatus.className}`} role="status">
              {offerStatus.label}
            </span>
          )}
        </div>
        {loading && <LoadingState label="Checking your assigned offer" />}
        {!loading && error && <ErrorState message={error} retry={loadAssignedOffer} />}
        {!loading && !error && result?.assigned && result.intervention && (
          <div className="assigned-offer-empty">
            <span className="gift-outline"><Gift size={24} /></span>
            <h2>{result.intervention.offer.name}</h2>
            <p>{result.intervention.offer.description}</p>
            {result.intervention.offer.discount_percentage !== null && (
              <strong>{result.intervention.offer.discount_percentage}% off</strong>
            )}
            <p className="offer-terms">
              <strong>Offer given on:</strong> {new Date(result.intervention.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}
            </p>
            <p className="offer-terms">
              <strong>Valid until:</strong> {new Date(result.intervention.expires_at).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}
            </p>
            {!result.intervention.expired && <p className="offer-terms">Enjoy this offer until {new Date(result.intervention.expires_at).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}!</p>}
            {result.intervention.expired && <p className="offer-terms" role="status">This offer has expired.</p>}
            {result.intervention.redeemed ? (
              <p className="offer-terms" role="status">Your offer has been used.</p>
            ) : result.intervention.claimed ? (
              <div role="status">
                <p className="offer-terms">Your offer has been claimed!</p>
                {result.intervention.claimed_at && <p className="offer-terms">Claimed on {new Date(result.intervention.claimed_at).toLocaleString("en-IN")}.</p>}
              </div>
            ) : !result.intervention.expired && <button className="button button-dark" type="button" onClick={claimOffer} disabled={claiming}>
              {claiming ? "Claiming…" : "Claim Offer"}
            </button>}
            {claimError && <p className="form-feedback form-error" role="alert">{claimError}</p>}
          </div>
        )}
        {!loading && !error && result && !result.assigned && (
          <div className="assigned-offer-empty">
            <span className="gift-outline"><Gift size={24} /></span>
            <h2>No personal offer is currently assigned.</h2>
            <p>There is no retention offer assigned to this account right now.</p>
            <Link to="/orders" className="quiet-link">View your orders <ArrowUpRight size={15} /></Link>
          </div>
        )}
      </div>
    </section>
  );
}
