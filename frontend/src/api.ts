import axios from 'axios'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'

const api = axios.create({ baseURL: BASE })

// ── types ──────────────────────────────────────────────────────────────────

export type Verdict = 'BLOCK' | 'REVIEW' | 'CLEAR'
export type RiskBand = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface DashboardStats {
  verdict_distribution: Record<Verdict, number>
  risk_band_counts: Record<string, number>
  verdicts_differ_count: number
  verdicts_differ_pct: number
  total_accounts: number
  total_screening_events: number
  top_risk_accounts: {
    account_id: string
    full_name: string
    overall_risk_score: number
    risk_band: RiskBand
    latest_verdict: Verdict
    match_score: number
  }[]
}

export interface AccountSummary {
  account_id: string
  full_name: string
  account_type: string
  kyc_status: string
  account_status: string
  overall_risk_score: number
  risk_band: RiskBand
  latest_verdict: Verdict
  latest_match_score: number
  created_at: string
}

export interface AccountsResponse {
  total: number
  page: number
  limit: number
  accounts: AccountSummary[]
}

export interface FeatureContribution {
  feature: string
  importance: number
  value: number
  contribution_pct: number
}

export interface ModelOutput {
  verdict: Verdict
  block_probability: number
  class_probabilities: Record<Verdict, number>
  audit_narrative: string
  audit_factors: string[]
  feature_contributions: FeatureContribution[]
  risk_components: Record<string, number>
}

export interface ThresholdExplanation {
  dynamic_t_block: number
  dynamic_t_review: number
  static_threshold: number
  baseline_t_block: number
  baseline_t_review: number
  adjustment_factor: number
  risk_deviation: string
  adjustment: string
  t_block_unclamped: string
  t_block_clamp_range: string
  t_block_final: number
  t_review_unclamped: string
  t_review_clamp_range: string
  t_review_final: number
  static_vs_dynamic: string
  interpretation: string
  decision_zones: Record<Verdict, string>
}

export interface AccountDetail {
  account: {
    account_id: string
    full_name: string
    account_type: string
    kyc_completeness: number
    kyc_status: string
    is_pep: number
    has_complex_ownership: number
    shell_company_flag: number
    activity_tier: string
    account_status: string
    country_residence: string
    created_at: string
  }
  risk_score: {
    overall_risk_score: number
    risk_band: RiskBand
    geographic_risk: number
    identity_kyc_risk: number
    pep_sanctions_risk: number
    behavioural_risk: number
    relationship_network_risk: number
    scored_at: string
    risk_formula?: string
  }
  latest_screening: {
    screening_id: string
    verdict: Verdict
    match_score: number
    context: string
    screened_at: string
  } | null
  threshold_decision: {
    t_block: number
    t_review: number
    match_score: number
    verdict: Verdict
    zone: string
  }
  audit: ModelOutput
}

export interface GraphNode {
  id: string
  type: 'source' | 'account' | 'wallet' | 'external'
  label: string
  overall_risk_score?: number | null
  risk_band?: RiskBand | null
  latest_verdict?: Verdict | null
  account_type?: string
  kyc_status?: string
  is_pep?: number
  country_residence?: string
  country?: string
  chain?: string | null
  is_sanctioned?: boolean | null
  sanctioned_entity_id?: string | null
  owner_account_id?: string | null
  transaction_count?: number
  total_amount?: number
  avg_amount?: number
  currencies?: Record<string, number>
  payment_rails?: Record<string, number>
  first_transaction?: string
  last_transaction?: string
}

export interface GraphEdge {
  from: string
  to: string
  recipient_type: string
  transaction_count: number
  total_amount: number
  avg_amount: number
  currencies: Record<string, number>
  payment_rails: Record<string, number>
  first_transaction: string
  last_transaction: string
}

export interface TransactionScreening {
  screening_id: string
  match_score: number
  dynamic_verdict: Verdict
  dynamic_t_block: number
  dynamic_t_review: number
  static_verdict: Verdict
  static_threshold: number
  verdicts_differ: boolean
}

export interface Transaction {
  transaction_id: string
  amount: number
  currency: string
  payment_rail: string
  recipient_type: string
  recipient_account_id: string | null
  recipient_wallet_id: string | null
  recipient_name: string | null
  recipient_country: string
  recipient_full_name: string | null
  recipient_risk_score: number | null
  recipient_risk_band: RiskBand | null
  recipient_is_sanctioned: boolean | null
  timestamp: string
  velocity_30d_count: number
  velocity_30d_amount: number
  is_first_time_recipient: number
  hour_of_day: number
  day_of_week: number
  screening: TransactionScreening | null
}

export interface Relationship {
  relationship_id: string
  related_entity_name: string
  relationship_type: string
  related_is_pep: boolean
  related_is_sanctioned: boolean
  sanctioned_entity_id: string | null
  source: string
}

export interface TransactionsResponse {
  account_id: string
  account: AccountDetail['account']
  risk_score: AccountDetail['risk_score']
  model_output: ModelOutput
  threshold_explanation: ThresholdExplanation
  relationships: Relationship[]
  relationship_count: number
  summary: {
    total_transactions: number
    total_sent_amount: number
    avg_transaction_amount: number
    max_transaction_amount: number
    unique_recipients: number
    date_range: { first: string; last: string }
    payment_rails: Record<string, number>
    currencies: Record<string, number>
    screening_verdicts: Record<string, number>
  }
  transaction_graph: {
    node_count: number
    edge_count: number
    nodes: GraphNode[]
    edges: GraphEdge[]
  }
  transactions: Transaction[]
  total: number
  page: number
  limit: number
}

export interface ScreeningResult {
  screening_id: string
  account_id: string
  verdict: Verdict
  match_score: number
  context: string
  t_block: number
  t_review: number
  verdicts_differ: boolean
  screened_at: string
}

export interface ScreeningListResponse {
  total: number
  page: number
  limit: number
  results: ScreeningResult[]
}

export interface ScreenRequest {
  account_type: string
  kyc_completeness: number
  kyc_status: string
  is_pep: number
  has_complex_ownership: number
  shell_company_flag: number
  activity_tier: string
  account_status: string
  match_score: number
  shares_address_with_sanctioned: number
  pep_exposure_score: number
  country_risk_score: number
  geographic_risk: number
  identity_kyc_risk: number
  pep_sanctions_risk: number
  behavioural_risk: number
  relationship_network_risk: number
  overall_risk_score: number
  override_applied: number
}

export interface ScreenResponse extends ModelOutput {
  t_block: number
  t_review: number
  match_score: number
  overall_risk_score: number
}

// ── API calls ──────────────────────────────────────────────────────────────

export const getDashboardStats = () =>
  api.get<DashboardStats>('/dashboard/stats').then(r => r.data)

export const getAccounts = (params: {
  page?: number
  limit?: number
  risk_band?: string
  verdict?: string
  search?: string
}) => api.get<AccountsResponse>('/accounts', { params }).then(r => r.data)

export const getAccount = (id: string) =>
  api.get<AccountDetail>(`/accounts/${id}`).then(r => r.data)

export const getTransactions = (id: string, params: {
  page?: number
  limit?: number
  from?: string
  to?: string
}) => api.get<TransactionsResponse>(`/accounts/${id}/transactions`, { params }).then(r => r.data)

export const getScreeningQueue = (params: {
  verdict?: string
  context?: string
  min_match_score?: number
  verdicts_differ?: boolean
  page?: number
  limit?: number
}) => api.get<ScreeningListResponse>('/screening', { params }).then(r => r.data)

export const screen = (body: ScreenRequest) =>
  api.post<ScreenResponse>('/screen', body).then(r => r.data)

export const explainThresholds = (id: string) =>
  api.get(`/thresholds/explain/${id}`).then(r => r.data)
