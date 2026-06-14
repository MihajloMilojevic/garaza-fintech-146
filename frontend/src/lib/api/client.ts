const API_BASE =
  ((import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail: string = res.statusText;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

export type Verdict = "BLOCK" | "REVIEW" | "CLEAR";
export type RiskBand = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type ScreeningContext = "account" | "transaction";

export interface DashboardStats {
  verdict_distribution: Record<Verdict, number>;
  risk_band_counts: { low: number; medium: number; high: number; critical: number };
  verdicts_differ_count: number;
  verdicts_differ_pct: number;
  total_accounts: number;
  total_screening_events: number;
  top_risk_accounts: Array<{
    account_id: string;
    full_name: string;
    overall_risk_score: number;
    risk_band: RiskBand;
    latest_verdict: Verdict;
    match_score: number;
  }>;
}

export interface AccountListItem {
  account_id: string;
  full_name: string;
  account_type: string;
  kyc_status: string;
  account_status: string;
  overall_risk_score: number;
  risk_band: RiskBand;
  latest_verdict: Verdict;
  latest_match_score: number;
  created_at: string;
}
export interface AccountListResponse {
  total: number;
  page: number;
  limit: number;
  accounts: AccountListItem[];
}

export interface FeatureContribution {
  feature: string;
  importance: number;
  value: number;
  contribution_pct: number;
}
export interface RiskComponents {
  geographic_risk: number;
  identity_kyc_risk: number;
  pep_sanctions_risk: number;
  behavioural_risk: number;
  relationship_network_risk: number;
}
export interface ClassProbabilities {
  BLOCK: number;
  CLEAR: number;
  REVIEW: number;
}

export interface AccountDetail {
  account: {
    account_id: string;
    full_name: string;
    account_type: string;
    kyc_completeness: number;
    kyc_status: string;
    is_pep: number;
    has_complex_ownership: number;
    shell_company_flag: number;
    activity_tier: string;
    account_status: string;
    country_residence: string;
    created_at: string;
  };
  risk_score: {
    overall_risk_score: number;
    risk_band: RiskBand;
    scored_at: string;
  } & RiskComponents;
  latest_screening: {
    screening_id: string;
    verdict: Verdict;
    match_score: number;
    context: ScreeningContext;
    screened_at: string;
  };
  threshold_decision: {
    t_block: number;
    t_review: number;
    match_score: number;
    verdict: Verdict;
    zone: string;
  };
  audit: {
    verdict: Verdict;
    block_probability: number;
    class_probabilities: ClassProbabilities;
    audit_narrative: string;
    audit_factors: string[];
    feature_contributions: FeatureContribution[];
    risk_components: RiskComponents;
  };
}

export interface Transaction {
  transaction_id: string;
  amount: number;
  currency: string;
  payment_rail: string;
  recipient_type: string;
  recipient_name: string | null;
  recipient_country: string;
  timestamp: string;
  velocity_30d_count: number;
  velocity_30d_amount: number;
  is_first_time_recipient: number;
}

export interface TransactionGraphNode {
  id: string;
  type: "source" | "account" | "wallet" | "external";
  label: string;
  overall_risk_score?: number;
  risk_band?: string;
  latest_verdict?: Verdict;
  country_residence?: string;
  country?: string;
  is_sanctioned?: boolean;
  chain?: string;
  transaction_count?: number;
  total_amount?: number;
  avg_amount?: number;
}
export interface TransactionGraphEdge {
  from: string;
  to: string;
  transaction_count: number;
  total_amount: number;
}
export interface TransactionGraph {
  node_count: number;
  edge_count: number;
  nodes: TransactionGraphNode[];
  edges: TransactionGraphEdge[];
}

export interface TransactionsResponse {
  account_id: string;
  total: number;
  page: number;
  limit: number;
  transactions: Transaction[];
  transaction_graph: TransactionGraph;
  summary: Record<string, unknown>;
  relationships: Array<Record<string, unknown>>;
  relationship_count: number;
}

export interface ScreeningListItem {
  screening_id: string;
  account_id: string;
  verdict: Verdict;
  match_score: number;
  context: ScreeningContext;
  t_block: number;
  t_review: number;
  verdicts_differ: boolean;
  screened_at: string;
}
export interface ScreeningListResponse {
  total: number;
  page: number;
  limit: number;
  results: ScreeningListItem[];
}

export interface ScreeningDetail {
  screening_id: string;
  account_id: string;
  verdict: Verdict;
  match_score: number;
  context: ScreeningContext;
  screened_at: string;
  threshold_decision: {
    t_block: number;
    t_review: number;
    match_score: number;
    verdict: Verdict;
    formula: Record<string, string | number>;
  };
  audit_narrative: string;
  audit_factors: string[];
  risk_components: RiskComponents;
  class_probabilities: ClassProbabilities;
  block_probability: number;
  feature_contributions: FeatureContribution[];
}

export interface ScreenRequest {
  match_score: number;
  overall_risk_score?: number;
  account_type?: "individual" | "business";
  kyc_status?: "complete" | "partial" | "pending" | "expired";
  kyc_completeness?: number;
  is_pep?: 0 | 1;
  has_complex_ownership?: 0 | 1;
  shell_company_flag?: 0 | 1;
  activity_tier?: "low" | "medium" | "high";
  account_status?: "active" | "suspended" | "closed";
  geographic_risk?: number;
  identity_kyc_risk?: number;
  pep_sanctions_risk?: number;
  behavioural_risk?: number;
  relationship_network_risk?: number;
  shares_address_with_sanctioned?: 0 | 1;
  pep_exposure_score?: number;
  country_risk_score?: number;
  override_applied?: 0 | 1;
}
export interface ScreenResponse {
  verdict: Verdict;
  t_block: number;
  t_review: number;
  match_score: number;
  overall_risk_score: number;
  block_probability: number;
  class_probabilities: ClassProbabilities;
  risk_components: RiskComponents;
  feature_contributions: FeatureContribution[];
  audit_narrative: string;
  audit_factors: string[];
}

export interface ThresholdExplain {
  account_id: string;
  overall_risk_score: number;
  t_block: number;
  t_review: number;
  formula: Record<string, string | number>;
  decision_zones: Record<string, string>;
}

export interface LlmReview {
  recommendation: "APPROVE" | "ESCALATE" | "BLOCK";
  confidence: "LOW" | "MEDIUM" | "HIGH";
  summary: string;
  key_concerns: string[];
  mitigating_factors: string[];
  required_actions: string[];
  compliance_notes: string;
  llm_powered: boolean;
  model?: string;
}

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const apiClient = {
  dashboardStats: () => api<DashboardStats>("/dashboard/stats"),
  listAccounts: (
    p: { page?: number; limit?: number; risk_band?: string; verdict?: string; search?: string } = {},
  ) => api<AccountListResponse>(`/accounts${qs(p)}`),
  account: (id: string) => api<AccountDetail>(`/accounts/${id}`),
  accountTransactions: (
    id: string,
    p: { page?: number; limit?: number; from?: string; to?: string } = {},
  ) => api<TransactionsResponse>(`/accounts/${id}/transactions${qs(p)}`),
  listScreening: (
    p: {
      page?: number;
      limit?: number;
      verdict?: string;
      context?: ScreeningContext;
      min_match_score?: number;
      verdicts_differ?: boolean;
    } = {},
  ) => api<ScreeningListResponse>(`/screening${qs(p)}`),
  screening: (id: string) => api<ScreeningDetail>(`/screening/${id}`),
  screen: (body: ScreenRequest) =>
    api<ScreenResponse>("/screen", { method: "POST", body: JSON.stringify(body) }),
  thresholdExplain: (id: string) => api<ThresholdExplain>(`/thresholds/explain/${id}`),
  llmReview: (id: string) =>
    api<LlmReview>(`/screening/${id}/llm-review`, { method: "POST" }),
};

export function verdictToRisk(v: Verdict): "low" | "medium" | "high" {
  return v === "BLOCK" ? "high" : v === "REVIEW" ? "medium" : "low";
}

export function verdictColor(v: Verdict): string {
  return v === "BLOCK" ? "#ef4444" : v === "REVIEW" ? "#f59e0b" : "#10b981";
}

export const API_BASE_URL = API_BASE;