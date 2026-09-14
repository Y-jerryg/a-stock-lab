import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, vi } from 'vitest';

import { CandidateDetailPage } from './CandidateDetailPage';

vi.mock('./IntradayChart', () => ({
  IntradayChart: () => <div role="img" aria-label="测试用日内分时图" />,
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

  expect(await screen.findByText('原始市场数据')).toBeInTheDocument();
  expect(screen.getByText('确定性计算')).toBeInTheDocument();
  expect(screen.getByText('AI 解释')).toBeInTheDocument();
  expect(screen.getByText('截止时点前已核实的公告。')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /示例来源/ })).toHaveAttribute(
    'href',
    'https://example.com/disclosure',
  );
  expect(screen.getByText('tail-radar-intraday-v2')).toBeInTheDocument();
  expect(screen.getByText('tail-radar-research-v2')).toBeInTheDocument();
  expect(screen.getByText('截止时点前可获得')).toBeInTheDocument();
  expect(screen.getByText(/检索时间 2026\/08\/28 14:35:00/)).toBeInTheDocument();
});

it('does not call paid research until the user confirms one candidate', async () => {
  const candidateId = '55555555-5555-4555-8555-555555555555';
  const original = candidatePayload(candidateId);
  const pending = {
    ...original,
    web_research: null,
    workflow_state: {
      ...original.workflow_state,
      research_status: 'pending',
    },
  };
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const inputUrl =
      input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    const path = new URL(inputUrl, 'http://localhost').pathname;
    const payload = path.endsWith('/research-availability')
      ? {
          enabled: true,
          model_identifier: 'gpt-5.6-sol',
          one_candidate_per_request: true,
          requires_user_api_key: true,
          automatic_batch_research: false,
        }
      : init?.method === 'POST'
        ? original.web_research
        : pending;
    return Promise.resolve(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  });
  vi.stubGlobal('fetch', fetchMock);
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

  const button = await screen.findByRole('button', { name: '确认并分析当前股票' });
  expect(
    fetchMock.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === 'POST'),
  ).toHaveLength(0);

  fireEvent.change(screen.getByPlaceholderText('输入你自己的 OpenAI 接口密钥'), {
    target: { value: 'test-user-api-key' },
  });
  fireEvent.click(screen.getByLabelText(/我确认仅分析当前股票，并理解这一次操作可能产生/));
  fireEvent.click(button);

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.filter(
        (call) => (call[1] as RequestInit | undefined)?.method === 'POST',
      ),
    ).toHaveLength(1);
  });
  const paidCall = fetchMock.mock.calls.find(
    (call) => (call[1] as RequestInit | undefined)?.method === 'POST',
  );
  const headers = new Headers((paidCall?.[1] as RequestInit | undefined)?.headers);
  expect(headers.get('X-OpenAI-API-Key')).toBe('test-user-api-key');
});

it('refreshes running research without submitting another paid request', async () => {
  const candidateId = '55555555-5555-4555-8555-555555555555';
  const original = candidatePayload(candidateId);
  let reads = 0;
  const fetchMock = vi.fn().mockImplementation((input: string, init?: RequestInit) => {
    expect(init?.method).not.toBe('POST');
    const payload = input.endsWith('/research-availability')
      ? { enabled: true, model_identifier: 'test-model' }
      : ++reads === 1
        ? {
            ...original,
            web_research: null,
            workflow_state: { ...original.workflow_state, research_status: 'running' },
          }
        : original;
    return Promise.resolve(new Response(JSON.stringify(payload)));
  });
  vi.stubGlobal('fetch', fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/tail-radar/candidates/${candidateId}`]}>
        <Routes>
          <Route path="/tail-radar/candidates/:candidateId" element={<CandidateDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole('button', { name: '当前股票正在分析' })).toBeDisabled();
  expect(
    await screen.findByText('基于证据的研究摘要。', {}, { timeout: 7_000 }),
  ).toBeInTheDocument();
  expect(reads).toBe(2);
  view.unmount();
  client.clear();
}, 10_000);

function candidatePayload(candidateId: string) {
  const asOf = '2026-08-28T14:35:00+08:00';
  const sourceId = '77777777-7777-4777-8777-777777777777';
  return {
    candidate_id: candidateId,
    run_id: '11111111-1111-4111-8111-111111111111',
    snapshot_id: '22222222-2222-4222-8222-222222222222',
    symbol: '600000',
    board: 'shanghai_main',
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
      concise_summary: '基于证据的研究摘要。',
      verified_facts: [
        {
          claim_id: 'fact_1',
          statement: '截止时点前已核实的公告。',
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
      unresolved_questions: ['价格变化的因果关系仍不确定。'],
      evidence_quality: 'medium',
      confidence: 0.68,
      sources: [
        {
          source_id: sourceId,
          url: 'https://example.com/disclosure',
          title: '示例来源',
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
      prompt_version: 'tail-radar-research-v2',
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
