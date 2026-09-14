import { apiClient } from '../../lib/api/client';

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type WorkflowLifecycle =
  | 'claimed'
  | 'snapshot_running'
  | 'screening_running'
  | 'candidate_analysis_running'
  | 'succeeded'
  | 'partial_success'
  | 'failed';
export type StageStatus = 'pending' | 'running' | 'succeeded' | 'no_evidence' | 'failed';
export type AShareBoard = 'shanghai_main' | 'shenzhen_main' | 'chinext' | 'star' | 'beijing';

export interface TailRadarRun {
  run_id: string;
  snapshot_id: string;
  trade_date: string;
  intended_snapshot_time: string;
  actual_started_at: string;
  actual_finished_at: string | null;
  status: RunStatus;
  screening_rule_version: string;
  is_official: boolean;
  evaluated_record_count: number | null;
  invalid_record_count: number | null;
  candidate_count: number | null;
  error_code: string | null;
}

export interface SnapshotQualityReport {
  passed: boolean;
  raw_record_count: number;
  normalized_record_count: number;
  duplicate_symbol_count: number;
  missing_symbol_count: number;
  invalid_price_count: number;
  invalid_pct_change_count: number;
  malformed_row_count: number;
  issues: string[];
}

export interface TailRadarWorkflow {
  workflow_run_id: string;
  workflow_version: string;
  lifecycle: WorkflowLifecycle;
  execution_status: RunStatus;
  analysis_as_of: string | null;
  candidate_count: number | null;
  technical_succeeded_count: number;
  technical_failed_count: number;
  technical_pending_count: number;
  research_succeeded_count: number;
  research_no_evidence_count: number;
  research_failed_count: number;
  research_pending_count: number;
  error_stage: string | null;
  error_code: string | null;
  actual_started_at: string;
  actual_finished_at: string | null;
}

export interface TailRadarRunSummary {
  run: TailRadarRun;
  workflow: TailRadarWorkflow | null;
  snapshot: {
    snapshot_run_id: string;
    snapshot_id: string;
    provider: string;
    provider_version: string | null;
    intended_snapshot_time: string;
    actual_fetch_started_at: string;
    actual_fetch_finished_at: string;
    provider_timestamp: string | null;
    persisted_at: string;
    latency_ms: number;
    row_count: number;
    schema_version: number;
    quality_report: SnapshotQualityReport;
  };
}

export interface TailRadarCandidateSummary {
  candidate_id: string;
  run_id: string;
  snapshot_id: string;
  symbol: string;
  exchange: string | null;
  board: AShareBoard | null;
  name: string | null;
  price: number;
  pct_change: number;
  amount: number | null;
  turnover_rate: number | null;
  amplitude: number | null;
  volume_ratio: number | null;
  float_market_cap: number | null;
  as_of: string;
  screening_rule_version: string;
  intraday_position: number | null;
  distance_from_high_pct: number | null;
  previous_5m_return_pct: number | null;
  previous_15m_return_pct: number | null;
  previous_30m_return_pct: number | null;
  technical_status: Exclude<StageStatus, 'no_evidence'> | null;
  research_status: StageStatus | null;
}

interface CandidatePage {
  items: TailRadarCandidateSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface IntradayBar {
  symbol: string;
  interval_minutes: number;
  ended_at: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  provider: string;
  provider_timestamp: string | null;
  fetched_at: string;
}

export interface ResearchClaim {
  claim_id: string;
  statement: string;
  classification: 'verified_fact' | 'interpretation' | 'insufficient_evidence';
  source_ids: string[];
}

export interface ResearchSource {
  source_id: string;
  url: string;
  title: string | null;
  publisher_domain: string;
  published_at: string | null;
  publication_timestamp_status: 'verified' | 'uncertain' | 'unavailable';
  availability_at_as_of: 'available_at_as_of' | 'published_after_as_of' | 'uncertain_at_as_of';
  retrieved_at: string;
  relationship_claim_ids: string[];
}

export interface ResearchAvailability {
  enabled: boolean;
  model_identifier: string;
  one_candidate_per_request: true;
  requires_user_api_key: true;
  automatic_batch_research: false;
}

export interface CandidateDetail {
  candidate_id: string;
  run_id: string;
  snapshot_id: string;
  symbol: string;
  board: AShareBoard | null;
  trade_date: string;
  as_of: string;
  screening_rule_version: string;
  rule_configuration: {
    pct_change_min: number;
    pct_change_max: number;
  };
  snapshot_evidence: {
    intended_snapshot_time: string;
    actual_fetch_started_at: string;
    actual_fetch_finished_at: string;
    provider: string;
    provider_timestamp: string | null;
    checksum_sha256: string;
    snapshot_schema_version: number;
  };
  snapshot_data: {
    symbol: string;
    exchange: string | null;
    name: string | null;
    price: number | null;
    pct_change: number | null;
    absolute_change: number | null;
    open: number | null;
    high: number | null;
    low: number | null;
    previous_close: number | null;
    volume: number | null;
    amount: number | null;
    amplitude: number | null;
    volume_ratio: number | null;
    turnover_rate: number | null;
    pe_dynamic: number | null;
    pb: number | null;
    total_market_cap: number | null;
    float_market_cap: number | null;
    provider: string;
    provider_timestamp: string | null;
    fetched_at: string;
  };
  decision: {
    outcome: 'included';
    reason: 'pct_change_in_inclusive_range';
    observed_pct_change: number;
    observed_price: number;
    inclusive_min: number;
    inclusive_max: number;
  };
  intraday_analysis: null | {
    analysis_id: string;
    analysis_as_of: string;
    used_bars: IntradayBar[] | null;
    latest_bar_used: IntradayBar | null;
    feature_schema_version: number;
    calculation_version: string;
    provider: string;
    provider_version: string | null;
    data_quality: {
      status: 'good' | 'degraded' | 'invalid';
      raw_bar_count: number;
      eligible_bar_count: number;
      used_bar_count: number;
      future_bar_count: number;
      duplicate_timestamp_count: number;
      missing_expected_bar_count: number;
      off_session_bar_count: number;
      normalization_issue_count: number;
      was_out_of_order: boolean;
      complete_from_market_open: boolean;
      issues: string[];
    };
    price: {
      previous_5m_return_pct: number | null;
      previous_15m_return_pct: number | null;
      previous_30m_return_pct: number | null;
      return_since_open_pct: number | null;
      distance_from_intraday_high_pct: number | null;
      distance_from_intraday_low_pct: number | null;
      normalized_intraday_position: number | null;
      drawdown_from_intraday_high_pct: number | null;
    };
    volume: {
      recent_5m_volume: number | null;
      previous_comparable_5m_volume: number | null;
      recent_volume_acceleration_ratio: number | null;
      recent_turnover_amount: number | null;
      vwap: number | null;
      distance_from_vwap_pct: number | null;
    };
    path: Record<string, boolean | null>;
    created_at: string;
  };
  web_research: null | {
    research_id: string;
    analysis_as_of: string;
    status: 'succeeded' | 'no_evidence';
    concise_summary: string;
    verified_facts: ResearchClaim[];
    likely_drivers: ResearchClaim[];
    company_context: ResearchClaim[];
    sector_context: ResearchClaim[];
    market_context: ResearchClaim[];
    positive_factors: ResearchClaim[];
    risk_factors: ResearchClaim[];
    unresolved_questions: string[];
    evidence_quality: 'high' | 'medium' | 'low' | 'insufficient';
    confidence: number;
    sources: ResearchSource[];
    provider: string;
    model_identifier: string;
    prompt_version: string;
    created_at: string;
  };
  workflow_state: null | {
    workflow_run_id: string;
    technical_status: Exclude<StageStatus, 'no_evidence'>;
    research_status: StageStatus;
    technical_error_code: string | null;
    research_error_code: string | null;
  };
  created_at: string;
}

export function getLatestRun() {
  return apiClient.get<TailRadarRun>('/api/v1/tail-radar/runs/latest');
}

export function getRunSummary(runId: string) {
  return apiClient.get<TailRadarRunSummary>(`/api/v1/tail-radar/runs/${runId}/summary`);
}

export async function getAllCandidates(runId: string): Promise<TailRadarCandidateSummary[]> {
  const first = await apiClient.get<CandidatePage>(
    `/api/v1/tail-radar/runs/${runId}/candidates?page=1&page_size=100`,
  );
  const items = [...first.items];
  const pageCount = Math.ceil(first.total / first.page_size);
  for (let page = 2; page <= pageCount; page += 1) {
    const result = await apiClient.get<CandidatePage>(
      `/api/v1/tail-radar/runs/${runId}/candidates?page=${String(page)}&page_size=100`,
    );
    items.push(...result.items);
  }
  return items;
}

export function getCandidate(candidateId: string) {
  return apiClient.get<CandidateDetail>(`/api/v1/tail-radar/candidates/${candidateId}`);
}

export function getResearchAvailability() {
  return apiClient.get<ResearchAvailability>('/api/v1/tail-radar/research-availability');
}

export function researchCandidate(candidateId: string, openaiApiKey: string, retryFailed: boolean) {
  return apiClient.post<NonNullable<CandidateDetail['web_research']>>(
    `/api/internal/v1/tail-radar/candidates/${candidateId}/research`,
    { confirmed: true, retry_failed: retryFailed },
    { 'X-OpenAI-API-Key': openaiApiKey },
  );
}
