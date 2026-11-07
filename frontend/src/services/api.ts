/** Typed calls for routes that already exist in the FastAPI backend. */
import { customerFacingApiError } from "./apiMessages.js";
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

export type HealthResponse = { status: string };

export type AccountUser = { id: number; email: string };
export type CustomerRegistration = { name: string; email: string; password: string };
export type CustomerLogin = { email: string; password: string };
export type AuthSession = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AccountUser;
};

export type CustomerOfferDetails = {
  name: string;
  description: string;
  discount_percentage: number | null;
};

export type AssignedRetentionIntervention = {
  created_at: string;
  expires_at: string;
  expired: boolean;
  offer: CustomerOfferDetails;
  claimed: boolean;
  claimed_at: string | null;
  redeemed: boolean;
};

export type CustomerRetentionOffer = {
  assigned: boolean;
  intervention: AssignedRetentionIntervention | null;
};
export type RetentionOfferClaim = {
  claimed: boolean;
  claimed_at: string | null;
  message: string;
};

export type StoreProduct = {
  id: number;
  name: string;
  category: string;
  price: string;
  stock: number;
};

export type CheckoutLine = { product_id: number; quantity: number };
export type OrderPricing = {
  subtotal_amount: string;
  discount_amount: string;
  applied_offer_name: string | null;
  applied_offer_description: string | null;
  shipping_fee: string;
  shipping_discount_amount: string;
  tax_rate_percent: number;
  tax_amount: string;
  total_amount: string;
};
export type OrderItem = {
  product_id: number;
  product_name: string;
  category: string;
  quantity: number;
  unit_price: string;
  line_total: string;
};
export type CustomerOrder = {
  id: number;
  status: string;
  created_at: string;
  total_amount: string;
  pricing: OrderPricing | null;
  items: OrderItem[];
};

export type RawCustomerFeatures = {
  Tenure: number;
  PreferredLoginDevice: string;
  CityTier: number;
  WarehouseToHome: number;
  PreferredPaymentMode: string;
  Gender: string;
  HourSpendOnApp: number;
  NumberOfDeviceRegistered: number;
  PreferedOrderCat: string;
  SatisfactionScore: number;
  MaritalStatus: string;
  NumberOfAddress: number;
  Complain: number;
  OrderAmountHikeFromlastYear: number;
  CouponUsed: number;
  OrderCount: number;
  DaySinceLastOrder: number;
  CashbackAmount: number;
};

export type Prediction = {
  customer_id: string | number;
  churn_probability: number;
  model_version: string;
};

export type RetentionCustomerInput = {
  customer_id: string | number;
  churn_probability: number;
  historical_revenue: number;
};

export type RetentionDecision = {
  customer_id: string | number;
  churn_probability: number;
  historical_revenue: number;
  priority_score: number;
  eligible: boolean;
  selected_intervention: string;
  estimated_intervention_cost: number;
  decision_explanation: string;
  budget_remaining: number;
};

export type RetentionSummary = {
  initial_budget: number;
  total_estimated_budget_allocated: number;
  remaining_budget: number;
  intervention_counts: Record<string, number>;
};

export type RetentionDecisionResponse = {
  customers: RetentionDecision[];
  summary: RetentionSummary;
};

export type RetentionRefreshResponse = {
  predictions: Prediction[];
  decisions: RetentionDecision[];
  summary: RetentionSummary;
};

export type AdminSession = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
};
export type AdminLogin = { email: string; password: string };
export type AdminAllocationDecision = {
  customer_id: number;
  customer_email?: string | null;
  has_feature_snapshot?: boolean;
  churn_probability: number | null;
  historical_revenue: number | null;
  priority_score: number | null;
  eligible?: boolean | null;
  intervention_code: string | null;
  estimated_intervention_cost: number | null;
  status?: string | null;
  preserved_existing_offer?: boolean;
  preserved_redeemed_offer?: boolean;
  new_offer_generated?: boolean;
};
export type AdminAllocationSummary = {
  initial_budget: number;
  total_estimated_budget_allocated: number;
  remaining_budget: number;
  intervention_counts: Record<string, number>;
  customer_count: number;
  skipped_customer_ids: number[];
  created_at: string;
  decisions: AdminAllocationDecision[];
  eligibility_threshold?: number | null;
  total_accounts?: number | null;
  customers_evaluated?: number | null;
  customers_missing_feature_snapshot?: number | null;
  customers_below_threshold?: number | null;
  customers_eligible?: number | null;
  customers_receiving_no_offer?: number | null;
  existing_offers_preserved?: number | null;
  existing_redeemed_offers_preserved?: number | null;
  new_offers_generated?: number | null;
  total_new_offer_cost?: number | null;
  total_committed_reserved_cost?: number | null;
};
export type AdminCurrentDecision = {
  customer_id: number;
  customer_email: string;
  has_feature_snapshot: boolean;
  churn_probability: number | null;
  historical_revenue: number | null;
  priority_score: number | null;
  intervention_code: string | null;
  estimated_intervention_cost: number | null;
  status: string | null;
  claim_status: "assigned" | "claimed" | "redeemed" | "no_offer" | null;
  claimed_at: string | null;
  redeemed_order_id: number | null;
  redemption_discount_amount: number | null;
  redemption_shipping_discount: number | null;
  free_shipping_applied: boolean;
  redeemed_at: string | null;
};
export type AdminDashboard = {
  total_customers: number;
  customers_with_predictions: number;
  customers_with_offers: number;
  customers_with_no_offer: number;
  intervention_counts: Record<string, number>;
  customers_without_feature_snapshot: number[];
  budget_configured: boolean;
  current_budget: number | null;
  latest_allocation: AdminAllocationSummary | null;
  current_decisions: AdminCurrentDecision[];
};
export type AdminBudget = { budget_configured: boolean; current_budget: number };
export type AdminCustomerEvaluation = {
  customer_id: number;
  customer_email: string;
  churn_probability: number;
  model_version: string;
  eligibility_threshold: number;
  eligible: boolean;
  intervention_code: string;
  estimated_intervention_cost: number;
  budget_available: number;
  budget_remaining: number;
  budget_allowed_assignment: boolean;
  decision_explanation: string;
};

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(customerFacingApiError(path, 0, ""), 0);
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof body?.detail === "string"
      ? body.detail
      : Array.isArray(body?.detail)
        ? body.detail.map((item: { msg?: string }) => item.msg ?? "Invalid request.").join(" ")
        : "";
    throw new ApiError(customerFacingApiError(path, response.status, detail), response.status);
  }
  return body as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  register: (customer: CustomerRegistration) =>
    request<AccountUser>("/auth/register", {
      method: "POST",
      body: JSON.stringify(customer),
    }),
  login: (credentials: CustomerLogin) =>
    request<AuthSession>("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),
  currentUser: (token: string) =>
    request<AccountUser>("/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    }),
  products: () => request<StoreProduct[]>("/products"),
  customerRetentionOffer: (token: string) =>
    request<CustomerRetentionOffer>("/retention/offer", {
      headers: { Authorization: `Bearer ${token}` },
    }),
  claimRetentionOffer: (token: string) =>
    request<RetentionOfferClaim>("/retention/offer/claim", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),
  checkout: (token: string, items: CheckoutLine[], applyRetentionOffer = false) =>
    request<CustomerOrder>("/orders/checkout", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ items, apply_retention_offer: applyRetentionOffer }),
    }),
  orderQuote: (token: string, items: CheckoutLine[], applyRetentionOffer = false) =>
    request<OrderPricing>("/orders/quote", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ items, apply_retention_offer: applyRetentionOffer }),
    }),
  orderHistory: (token: string) =>
    request<CustomerOrder[]>("/orders", {
      headers: { Authorization: `Bearer ${token}` },
    }),
  predict: (customer_id: string | number, features: RawCustomerFeatures) =>
    request<Prediction>("/predict", {
      method: "POST",
      body: JSON.stringify({ customer_id, features }),
    }),
  decideRetention: (customers: RetentionCustomerInput[], total_budget: number) =>
    request<RetentionDecisionResponse>("/retention/decide", {
      method: "POST",
      body: JSON.stringify({ customers, total_budget }),
    }),
  refreshRetention: (customer_ids: number[], total_budget: number) =>
    request<RetentionRefreshResponse>("/retention/refresh", {
      method: "POST",
      body: JSON.stringify({ customer_ids, total_budget }),
    }),
  adminLogin: (credentials: AdminLogin) =>
    request<AdminSession>("/admin/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),
  adminDashboard: (token: string) =>
    request<AdminDashboard>("/admin/dashboard", {
      headers: { Authorization: `Bearer ${token}` },
    }),
  saveAdminBudget: (token: string, total_budget: number) =>
    request<AdminBudget>("/admin/budget", {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ total_budget }),
    }),
  runAdminAllocation: (token: string) =>
    request<AdminDashboard>("/admin/retention/allocate", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    }),
  evaluateAllAdminCustomers: (token: string, eligibility_threshold: number) =>
    request<AdminDashboard>("/admin/retention/evaluate-all", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ eligibility_threshold }),
    }),
  evaluateAdminCustomer: (token: string, customer_id: number, eligibility_threshold: number) =>
    request<AdminCustomerEvaluation>(`/admin/customers/${customer_id}/evaluate`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ eligibility_threshold }),
    }),
};
