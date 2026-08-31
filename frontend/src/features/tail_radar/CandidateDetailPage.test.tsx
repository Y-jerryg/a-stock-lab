import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, vi } from 'vitest';

import { CandidateDetailPage } from './CandidateDetailPage';

vi.mock('./IntradayChart', () => ({
  IntradayChart: () => <div role="img" aria-label="fixture intraday chart" />,
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

it('visually and semantically separates market facts, deterministic features, and AI interpretation', async () => {
  const candidateId = '55555555-5555-4555-8555-555555555555';
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(candidatePayload(candidateId)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/tail-radar/candidates/${candidateId}`]}>
        <Routes>
          <Route path="/tail-radar/candidates/:candidateId" element={<CandidateDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText('Raw market data')).toBeInTheDocument();
  expect(screen.getByText('Deterministic calculations')).toBeInTheDocument();
  expect(screen.getByText('AI interpretation')).toBeInTheDocument();
  expect(screen.getByText('Verified disclosure before cutoff.')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Fixture source/ })).toHaveAttribute(
    'href',
    'https://example.com/disclosure',
  );
  expect(screen.getByText('tail-radar-intraday-v2')).toBeInTheDocument();
  expect(screen.getByText('tail-radar-research-v1')).toBeInTheDocument();
  expect(screen.getByText('available at as of')).toBeInTheDocument();
  expect(screen.getByText(/retrieved 2026\/08\/28 14:35:00/)).toBeInTheDocument();
});

function candidatePayload(candidateId: string) {
  const asOf = '2026-08-28T14:35:00+08:00';
  const sourceId = '77777777-7777-4777-8777-777777777777';
  return {
    candidate_id: candidateId,
    run_id: '11111111-1111-4111-8111-111111111111',
    snapshot_id: '22222222-2222-4222-8222-222222222222',
    symbol: '600000',
    trade_date: '2026-08-28',
    as_of: '2026-08-28T14:30:02+08:00',
    screening_rule_version: 'tail-radar-screen-v1',
    rule_configuration: { pct_change_min: 2, pct_change_max: 3 },
    snapshot_evidence: {
      intended_snapshot_time: '2026-08-28T14:30:00+08:00',
      actual_fetch_started_at: '2026-08-28T14:30:01+08:00',
      actual_fetch_finished_at: '2026-08-28T14:30:02+08:00',
      provider: 'fixture',
      provider_timestamp: null,
      checksum_sha256: 'a'.repeat(64),
      snapshot_schema_version: 2,
    },
    snapshot_data: {
      symbol: '600000',
      name: '浦发银行',
      price: 10.25,
      pct_change: 2.5,
      amount: 100000000,
      turnover_rate: 1.2,
      provider: 'fixture',
      fetched_at: '2026-08-28T14:30:02+08:00',
    },
    decision: {
      outcome: 'included',
      reason: 'pct_change_in_inclusive_range',
      observed_pct_change: 2.5,
      observed_price: 10.25,
      inclusive_min: 2,
      inclusive_max: 3,
    },
    intraday_analysis: {
      analysis_id: '66666666-6666-4666-8666-666666666666',
      analysis_as_of: asOf,
      used_bars: [],
      latest_bar_used: null,
      feature_schema_version: 2,
      calculation_version: 'tail-radar-intraday-v2',
      provider: 'fixture',
      provider_version: 'fixture-1',
      data_quality: {
        status: 'degraded',
        used_bar_count: 0,
        future_bar_count: 0,
        missing_expected_bar_count: 1,
        complete_from_market_open: false,
      },
      price: {},
      volume: {},
      path: { steady_strengthening: null },
      created_at: asOf,
    },
    web_research: {
      research_id: '88888888-8888-4888-8888-888888888888',
      analysis_as_of: asOf,
      status: 'succeeded',
      concise_summary: 'Evidence-backed summary.',
      verified_facts: [
        {
          claim_id: 'fact_1',
          statement: 'Verified disclosure before cutoff.',
          classification: 'verified_fact',
          source_ids: [sourceId],
        },
      ],
      likely_drivers: [],
      company_context: [],
      sector_context: [],
      market_context: [],
      positive_factors: [],
      risk_factors: [],
      unresolved_questions: ['Causality remains uncertain.'],
      evidence_quality: 'medium',
      confidence: 0.68,
      sources: [
        {
          source_id: sourceId,
          url: 'https://example.com/disclosure',
          title: 'Fixture source',
          publisher_domain: 'example.com',
          published_at: '2026-08-28T10:00:00+08:00',
          publication_timestamp_status: 'verified',
          availability_at_as_of: 'available_at_as_of',
          retrieved_at: asOf,
          relationship_claim_ids: ['fact_1'],
        },
      ],
      provider: 'openai',
      model_identifier: 'fixture-model',
      prompt_version: 'tail-radar-research-v1',
      created_at: asOf,
    },
    workflow_state: {
      workflow_run_id: '99999999-9999-4999-8999-999999999999',
      technical_status: 'succeeded',
      research_status: 'succeeded',
      technical_error_code: null,
      research_error_code: null,
    },
    created_at: asOf,
  };
}
