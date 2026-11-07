import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { LogOut, RefreshCw, Save } from "lucide-react";
import { ErrorState, LoadingState } from "../components/PageState";
import { formatRupees } from "../data/products";
import { api, ApiError } from "../services/api";
import type { AdminCustomerEvaluation, AdminDashboard } from "../services/api";

const ADMIN_SESSION_KEY = "littleleaf-admin-session-v1";

export function AdminDashboardPage() {
  const [token, setToken] = useState(() => window.sessionStorage.getItem(ADMIN_SESSION_KEY));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null);
  const [budgetInput, setBudgetInput] = useState("");
  const [selectedCustomerId, setSelectedCustomerId] = useState("");
  const [thresholdPercent, setThresholdPercent] = useState(30);
  const [evaluation, setEvaluation] = useState<AdminCustomerEvaluation | null>(null);
  const [loading, setLoading] = useState(Boolean(token));
  const [saving, setSaving] = useState(false);
  const [bulkEvaluating, setBulkEvaluating] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const clearAdminSession = useCallback(() => {
    window.sessionStorage.removeItem(ADMIN_SESSION_KEY);
    setToken(null);
    setDashboard(null);
    setPassword("");
  }, []);

  const loadDashboard = useCallback(async (authToken: string) => {
    setLoading(true);
    setError("");
    try {
      const result = await api.adminDashboard(authToken);
      setDashboard(result);
      setBudgetInput(result.current_budget === null ? "" : String(result.current_budget));
      setSelectedCustomerId((current) => {
        if (current && result.current_decisions.some((row) => String(row.customer_id) === current && row.has_feature_snapshot)) return current;
        const firstWithSnapshot = result.current_decisions.find((row) => row.has_feature_snapshot);
        return firstWithSnapshot ? String(firstWithSnapshot.customer_id) : "";
      });
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) clearAdminSession();
      setError(reason instanceof Error ? reason.message : "The admin dashboard could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [clearAdminSession]);

  useEffect(() => {
    if (token) void loadDashboard(token);
  }, [token, loadDashboard]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const session = await api.adminLogin({ email, password });
      window.sessionStorage.setItem(ADMIN_SESSION_KEY, session.access_token);
      setPassword("");
      setToken(session.access_token);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Administrator sign-in failed.");
      setLoading(false);
    }
  }

  async function saveBudget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || budgetInput.trim() === "") return;
    const amount = Number(budgetInput);
    if (!Number.isFinite(amount) || amount < 0) {
      setError("Enter a valid non-negative budget in INR.");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await api.saveAdminBudget(token, amount);
      await loadDashboard(token);
      setNotice("Budget saved. Existing decisions remain in place until you run a new allocation.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The budget could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function evaluateAllCustomers() {
    if (!token || !dashboard?.budget_configured || dashboard.current_budget === null) return;
    const confirmed = window.confirm(
      `Evaluate every customer with saved feature data using a ${(thresholdPercent).toFixed(0)}% eligibility threshold and the saved ${formatRupees(dashboard.current_budget)} budget? Redeemed offers and active unexpired offers will be preserved.`,
    );
    if (!confirmed) return;
    setBulkEvaluating(true);
    setError("");
    setNotice("");
    try {
      const updated = await api.evaluateAllAdminCustomers(token, thresholdPercent / 100);
      setDashboard(updated);
      setBudgetInput(updated.current_budget === null ? "" : String(updated.current_budget));
      setNotice("Bulk evaluation completed and persisted. Existing protected offers were preserved.");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) clearAdminSession();
      setError(reason instanceof Error ? reason.message : "Bulk retention evaluation failed.");
    } finally {
      setBulkEvaluating(false);
    }
  }

  async function evaluateCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedCustomerId) return;
    setEvaluating(true);
    setError("");
    setNotice("");
    setEvaluation(null);
    try {
      const result = await api.evaluateAdminCustomer(
        token,
        Number(selectedCustomerId),
        thresholdPercent / 100,
      );
      setEvaluation(result);
      await loadDashboard(token);
      setNotice("Customer evaluation completed and persisted.");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) clearAdminSession();
      setError(reason instanceof Error ? reason.message : "Customer evaluation failed.");
    } finally {
      setEvaluating(false);
    }
  }

  if (!token) {
    return (
      <section className="page-shell admin-page account-page">
        <div className="account-form-panel">
          <span className="eyebrow">LittleLeaf administration</span>
          <h1>Administrator sign in</h1>
          <p className="account-intro">Use the administrator credentials configured for this backend.</p>
          {error && <div className="form-feedback error" role="alert">{error}</div>}
          <form className="form-stack" onSubmit={signIn}>
            <label htmlFor="admin-email">Administrator email</label>
            <input id="admin-email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} />
            <label htmlFor="admin-password">Password</label>
            <input id="admin-password" type="password" autoComplete="current-password" minLength={4} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} />
            <button className="button button-dark" type="submit" disabled={loading}>{loading ? "Signing in…" : "Sign in"}</button>
          </form>
        </div>
      </section>
    );
  }

  if (loading && !dashboard) return <section className="page-shell admin-page"><LoadingState label="Loading administrator dashboard" /></section>;

  return (
    <section className="page-shell admin-page">
      <header className="admin-heading">
        <div><span className="eyebrow">LittleLeaf administration</span><h1>Retention overview</h1><p>Customer predictions and persisted intervention decisions.</p></div>
        <button className="button button-light" type="button" onClick={clearAdminSession}><LogOut size={16} /> Sign out</button>
      </header>
      {error && <div className="admin-feedback error" role="alert">{error}</div>}
      {notice && <div className="admin-feedback success" role="status">{notice}</div>}
      {loading && <LoadingState label="Refreshing dashboard data" />}
      {!dashboard && !loading && <ErrorState message="The administrator dashboard is unavailable." retry={() => token && loadDashboard(token)} />}
      {dashboard && <>
        <div className="admin-metrics">
          <Metric label="Registered customers" value={dashboard.total_customers} />
          <Metric label="With churn predictions" value={dashboard.customers_with_predictions} />
          <Metric label="Currently receiving offers" value={dashboard.customers_with_offers} />
          <Metric label="Currently receiving no offer" value={dashboard.customers_with_no_offer} />
        </div>

        <section className="admin-panel">
          <div className="admin-panel-heading"><div><span className="eyebrow">Budget management</span><h2>Retention budget</h2></div><span className="admin-current-budget">{dashboard.budget_configured ? formatRupees(dashboard.current_budget ?? 0) : "Not configured"}</span></div>
          <form className="admin-budget-form" onSubmit={saveBudget}>
            <label htmlFor="retention-budget">Available budget (INR)</label>
            <input id="retention-budget" type="number" min="0" step="0.01" required value={budgetInput} onChange={(event) => setBudgetInput(event.target.value)} />
            <button className="button button-dark" type="submit" disabled={saving || budgetInput.trim() === ""}><Save size={15} /> {saving ? "Saving…" : "Save budget"}</button>
          </form>
          <p className="admin-help">Save any budget change before running a bulk evaluation. Saving changes the stored budget only; customer decisions change only after the explicit bulk action.</p>
          {dashboard.customers_without_feature_snapshot.length > 0 && <p className="admin-warning">Customers without saved model features are excluded from allocation: {dashboard.customers_without_feature_snapshot.join(", ")}.</p>}
          <div className="admin-breakdown"><strong>Current intervention breakdown</strong>{Object.keys(dashboard.intervention_counts).length === 0 ? <span>No persisted decisions yet.</span> : Object.entries(dashboard.intervention_counts).map(([code, count]) => <span key={code}>{code.replaceAll("_", " ")}: {count}</span>)}</div>
          <div className="admin-bulk-action">
            <div>
              <strong>Evaluate all customers &amp; generate offers</strong>
              <p className="admin-help">Runs model inference once for all valid saved snapshots, applies the threshold above, and allocates within the saved budget. Active unexpired and redeemed offers are preserved and their costs reserved.</p>
            </div>
            <button className="button button-dark" type="button" onClick={evaluateAllCustomers} disabled={bulkEvaluating || !dashboard.budget_configured || dashboard.current_budget === null}>
              <RefreshCw size={15} /> {bulkEvaluating ? "Evaluating customers…" : "Evaluate All Customers & Generate Offers"}
            </button>
          </div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-heading"><div><span className="eyebrow">Live customer evaluation</span><h2>Evaluate &amp; generate offer</h2></div></div>
          <p className="admin-help">The threshold controls business eligibility only; it does not change the trained churn model or its prediction.</p>
          <form className="admin-evaluation-form" onSubmit={evaluateCustomer}>
            <label htmlFor="evaluation-customer">Customer account</label>
            <select id="evaluation-customer" required value={selectedCustomerId} onChange={(event) => setSelectedCustomerId(event.target.value)}>
              <option value="">Select a customer</option>
              {dashboard.current_decisions.map((customer) => <option key={customer.customer_id} value={customer.customer_id} disabled={!customer.has_feature_snapshot}>
                {customer.customer_email} {!customer.has_feature_snapshot ? "(no feature snapshot)" : ""}
              </option>)}
            </select>
            <label htmlFor="eligibility-threshold">Minimum churn probability: <strong>{thresholdPercent}%</strong></label>
            <input id="eligibility-threshold" type="range" min="10" max="90" step="1" value={thresholdPercent} onChange={(event) => setThresholdPercent(Number(event.target.value))} />
            <button className="button button-dark" type="submit" disabled={evaluating || !selectedCustomerId || !dashboard.budget_configured}>
              <RefreshCw size={15} /> {evaluating ? "Evaluating…" : "Evaluate & Generate Offer"}
            </button>
          </form>
          {!dashboard.budget_configured && <p className="admin-warning">Save the retention budget before evaluating a customer.</p>}
          {evaluation && <div className="admin-evaluation-result" role="status">
            <strong>{evaluation.customer_email}</strong>
            <span>Churn probability: {(evaluation.churn_probability * 100).toFixed(2)}%</span>
            <span>Eligibility: {evaluation.eligible ? "Qualifies" : "Below threshold"} at {(evaluation.eligibility_threshold * 100).toFixed(0)}%</span>
            <span>Intervention: {evaluation.intervention_code.replaceAll("_", " ")}</span>
            <span>Estimated cost: {formatRupees(evaluation.estimated_intervention_cost)}</span>
            <span>Budget available: {formatRupees(evaluation.budget_available)} · remaining: {formatRupees(evaluation.budget_remaining)}</span>
            {!evaluation.budget_allowed_assignment && evaluation.eligible && <span>The selected paid offer did not fit the available budget.</span>}
            <span>{evaluation.decision_explanation}</span>
          </div>}
        </section>

        <section className="admin-panel">
          <div className="admin-panel-heading"><div><span className="eyebrow">Persisted run</span><h2>Latest allocation results</h2></div></div>
          {dashboard.latest_allocation ? <>
            <div className="admin-run-summary">
              {dashboard.latest_allocation.eligibility_threshold !== null && dashboard.latest_allocation.eligibility_threshold !== undefined && <span>Eligibility threshold: <strong>{(dashboard.latest_allocation.eligibility_threshold * 100).toFixed(0)}%</strong></span>}
              {dashboard.latest_allocation.total_accounts !== null && dashboard.latest_allocation.total_accounts !== undefined && <span>Total accounts: <strong>{dashboard.latest_allocation.total_accounts}</strong></span>}
              {dashboard.latest_allocation.customers_evaluated !== null && dashboard.latest_allocation.customers_evaluated !== undefined && <span>Evaluated: <strong>{dashboard.latest_allocation.customers_evaluated}</strong></span>}
              {dashboard.latest_allocation.customers_missing_feature_snapshot !== null && dashboard.latest_allocation.customers_missing_feature_snapshot !== undefined && <span>Missing feature data: <strong>{dashboard.latest_allocation.customers_missing_feature_snapshot}</strong></span>}
              {dashboard.latest_allocation.customers_below_threshold !== null && dashboard.latest_allocation.customers_below_threshold !== undefined && <span>Below threshold: <strong>{dashboard.latest_allocation.customers_below_threshold}</strong></span>}
              {dashboard.latest_allocation.customers_eligible !== null && dashboard.latest_allocation.customers_eligible !== undefined && <span>Eligible: <strong>{dashboard.latest_allocation.customers_eligible}</strong></span>}
              {dashboard.latest_allocation.customers_receiving_no_offer !== null && dashboard.latest_allocation.customers_receiving_no_offer !== undefined && <span>NO_OFFER: <strong>{dashboard.latest_allocation.customers_receiving_no_offer}</strong></span>}
              {dashboard.latest_allocation.existing_offers_preserved !== null && dashboard.latest_allocation.existing_offers_preserved !== undefined && <span>Existing offers preserved: <strong>{dashboard.latest_allocation.existing_offers_preserved}</strong></span>}
              {dashboard.latest_allocation.existing_redeemed_offers_preserved !== null && dashboard.latest_allocation.existing_redeemed_offers_preserved !== undefined && <span>Redeemed offers preserved: <strong>{dashboard.latest_allocation.existing_redeemed_offers_preserved}</strong></span>}
              {dashboard.latest_allocation.new_offers_generated !== null && dashboard.latest_allocation.new_offers_generated !== undefined && <span>New offers: <strong>{dashboard.latest_allocation.new_offers_generated}</strong></span>}
              {dashboard.latest_allocation.total_committed_reserved_cost !== null && dashboard.latest_allocation.total_committed_reserved_cost !== undefined && <span>Committed / reserved: <strong>{formatRupees(dashboard.latest_allocation.total_committed_reserved_cost)}</strong></span>}
              <span>Budget used: <strong>{formatRupees(dashboard.latest_allocation.initial_budget)}</strong></span>
              <span>New allocation: <strong>{formatRupees(dashboard.latest_allocation.total_new_offer_cost ?? dashboard.latest_allocation.total_estimated_budget_allocated)}</strong></span>
              <span>Remaining: <strong>{formatRupees(dashboard.latest_allocation.remaining_budget)}</strong></span>
              <span>Customers processed: <strong>{dashboard.latest_allocation.customer_count}</strong></span>
              <span>Run: <strong>{new Date(dashboard.latest_allocation.created_at).toLocaleString("en-IN")}</strong></span>
            </div>
            <div className="admin-breakdown"><strong>Interventions in this run</strong>{Object.entries(dashboard.latest_allocation.intervention_counts).map(([code, count]) => <span key={code}>{code.replaceAll("_", " ")}: {count}</span>)}</div>
          <DecisionTable rows={dashboard.latest_allocation.decisions} />
          </> : <p className="admin-help">No full administrator allocation has been persisted yet. Individual customer evaluations are recorded in the current customer records below. Saving a budget alone does not change customer decisions.</p>}
        </section>

        <section className="admin-panel">
          <div className="admin-panel-heading"><div><span className="eyebrow">Current records</span><h2>Latest customer decisions</h2></div></div>
          <DecisionTable rows={dashboard.current_decisions} showStatus />
        </section>
      </>}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <article className="admin-metric"><span>{label}</span><strong>{value}</strong></article>;
}

function DecisionTable({ rows, showStatus = false }: {
  rows: Array<{
    customer_id: number;
    customer_email?: string | null;
    has_feature_snapshot?: boolean;
    churn_probability: number | null;
    historical_revenue: number | null;
    priority_score: number | null;
    intervention_code: string | null;
    estimated_intervention_cost: number | null;
    status?: string | null;
    preserved_existing_offer?: boolean;
    preserved_redeemed_offer?: boolean;
    new_offer_generated?: boolean;
    claim_status?: "assigned" | "claimed" | "redeemed" | "no_offer" | null;
    claimed_at?: string | null;
    redeemed_order_id?: number | null;
    redemption_discount_amount?: number | null;
    redemption_shipping_discount?: number | null;
    free_shipping_applied?: boolean;
    redeemed_at?: string | null;
  }>;
  showStatus?: boolean;
}) {
  if (rows.length === 0) return <p className="admin-help">No customer decisions are available.</p>;
  return (
    <div className="admin-table-wrap"><table className="admin-table">
      <thead><tr><th>Customer</th><th>Churn probability</th><th>Historical revenue</th><th>Priority score</th><th>Intervention</th><th>Estimated cost</th>{showStatus && <><th>Intervention status</th><th>Offer / redemption</th></>}</tr></thead>
      <tbody>{rows.map((row) => (
        <tr key={row.customer_id}>
          <td>#{row.customer_id}{row.customer_email && <small className="admin-claim-time">{row.customer_email}</small>}{row.has_feature_snapshot === false && <small className="admin-claim-time">Missing feature data</small>}</td>
          <td>{row.has_feature_snapshot === false ? "Missing feature data" : row.churn_probability === null ? "Not evaluated" : `${(row.churn_probability * 100).toFixed(1)}%`}</td>
          <td>{row.historical_revenue === null ? "—" : formatRupees(row.historical_revenue)}</td>
          <td>{row.priority_score === null ? "—" : row.priority_score.toFixed(2)}</td>
          <td>{row.intervention_code ? row.intervention_code.replaceAll("_", " ") : row.has_feature_snapshot === false ? "Missing feature data" : "Not assigned"}{row.preserved_redeemed_offer && <small className="admin-claim-time">Redeemed offer preserved</small>}{row.preserved_existing_offer && !row.preserved_redeemed_offer && <small className="admin-claim-time">Existing offer preserved</small>}{row.new_offer_generated && <small className="admin-claim-time">New offer assigned</small>}</td>
          <td>{row.estimated_intervention_cost === null ? "—" : formatRupees(row.estimated_intervention_cost)}</td>
          {showStatus && <>
            <td>{row.status ?? "Not assigned"}</td>
            <td>
              {row.claim_status === "redeemed" ? <>
                Redeemed for order #{row.redeemed_order_id}
                {row.redemption_discount_amount !== null && row.redemption_discount_amount !== undefined && row.redemption_discount_amount > 0 && <small className="admin-claim-time">Discount: {formatRupees(row.redemption_discount_amount)}</small>}
                {row.free_shipping_applied && row.redemption_shipping_discount !== null && row.redemption_shipping_discount !== undefined && <small className="admin-claim-time">Shipping waived: {formatRupees(row.redemption_shipping_discount)}</small>}
                {row.redeemed_at && <small className="admin-claim-time">{new Date(row.redeemed_at).toLocaleString("en-IN")}</small>}
              </> : row.claim_status === "claimed" ? <>
                Offer claimed{row.claimed_at && <small className="admin-claim-time">{new Date(row.claimed_at).toLocaleString("en-IN")}</small>}
              </> : row.claim_status === "assigned" ? "Offer assigned · not claimed" : (row.intervention_code ? "No offer assigned" : "Not assigned")}
            </td>
          </>}
        </tr>
      ))}</tbody>
    </table></div>
  );
}
