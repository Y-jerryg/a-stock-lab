import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Routes, Route } from 'react-router-dom';
import { afterEach, beforeEach, vi } from 'vitest';

import { App } from './App';
import { CandidateDetailPage } from '../features/tail_radar/CandidateDetailPage';
import { TailRadarPage } from '../features/tail_radar/TailRadarPage';

vi.mock('../features/tail_radar/DailyChartPanel', () => ({ DailyChartPanel: () => null }));

describe('Tail Radar navigation', () => {
  beforeEach(() => {
    window.location.hash = '#/tail-radar';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the honest empty state when no persisted run exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: 'tail_radar_run_not_found', message: 'No run.' },
          }),
          { status: 404, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );
    render(<App />);

    expect(await screen.findByRole('heading', { name: '尾盘雷达', level: 1 })).toBeInTheDocument();
    expect(await screen.findByText('尚无尾盘雷达运行记录')).toBeInTheDocument();
    expect(screen.queryByText(/stock price/i)).not.toBeInTheDocument();
  });

  it.each([
    ['tail-radar-screen-v1', 2, 3, 2.5, '历史规则：涨幅含边界 +2.00% 至 +3.00%'],
    ['tail-radar-screen-v2', 3, 5, 4, '涨幅含边界 +3.00% 至 +5.00%'],
  ])('renders saved %s thresholds and candidates', async (version, min, max, pct, label) => {
    const run = {
      run_id: '11111111-1111-4111-8111-111111111111',
      snapshot_id: '22222222-2222-4222-8222-222222222222',
      trade_date: '2026-08-28',
      intended_snapshot_time: '2026-08-28T14:30:00+08:00',
      actual_started_at: '2026-08-28T14:31:00+08:00',
      actual_finished_at: '2026-08-28T14:31:01+08:00',
      status: 'succeeded',
      screening_rule_version: version,
      rule_configuration: { pct_change_min: min, pct_change_max: max },
      is_official: true,
      evaluated_record_count: 5000,
      invalid_record_count: 0,
      candidate_count: 1,
      error_code: null,
    };
    const responses: Record<string, object> = {
      '/api/v1/tail-radar/runs/latest': run,
      [`/api/v1/tail-radar/runs/${run.run_id}/summary`]: {
        run,
        workflow: {
          workflow_run_id: '33333333-3333-4333-8333-333333333333',
          workflow_version: 'tail-radar-workflow-v2',
          lifecycle: 'succeeded',
          execution_status: 'succeeded',
          analysis_as_of: '2026-08-28T14:35:00+08:00',
          candidate_count: 1,
          technical_succeeded_count: 1,
          technical_failed_count: 0,
          technical_pending_count: 0,
          research_succeeded_count: 0,
          research_no_evidence_count: 0,
          research_failed_count: 0,
          research_pending_count: 1,
          error_stage: null,
          error_code: null,
          actual_started_at: '2026-08-28T14:30:00+08:00',
          actual_finished_at: '2026-08-28T14:36:00+08:00',
        },
        snapshot: {
          snapshot_run_id: '44444444-4444-4444-8444-444444444444',
          snapshot_id: run.snapshot_id,
          provider: 'akshare',
          provider_version: 'fixture',
          intended_snapshot_time: run.intended_snapshot_time,
          actual_fetch_started_at: '2026-08-28T14:30:01+08:00',
          actual_fetch_finished_at: '2026-08-28T14:30:03+08:00',
          provider_timestamp: null,
          persisted_at: '2026-08-28T14:30:04+08:00',
          latency_ms: 2000,
          row_count: 5000,
          schema_version: 2,
          quality_report: { passed: true, issues: [] },
        },
      },
    };
    const candidatePage = {
      items: [
        {
          candidate_id: '55555555-5555-4555-8555-555555555555',
          run_id: run.run_id,
          snapshot_id: run.snapshot_id,
          symbol: '600000',
          exchange: 'SSE',
          board: 'shanghai_main',
          name: '浦发银行',
          price: 10.25,
          pct_change: pct,
          amount: 100000000,
          turnover_rate: 1.2,
          amplitude: 3.1,
          volume_ratio: 1.4,
          float_market_cap: 10000000000,
          as_of: '2026-08-28T14:30:03+08:00',
          screening_rule_version: 'tail-radar-screen-v1',
          intraday_position: 0.75,
          distance_from_high_pct: -0.2,
          previous_5m_return_pct: 0.1,
          previous_15m_return_pct: 0.3,
          previous_30m_return_pct: 0.5,
          technical_status: 'succeeded',
          research_status: 'pending',
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
    };
    const baseCandidate = candidatePage.items[0];
    if (!baseCandidate) throw new Error('Missing candidate fixture');
    candidatePage.items = Array.from({ length: 30 }, (_, i) => ({
      ...baseCandidate,
      candidate_id: `55555555-5555-4555-8555-${String(i).padStart(12, '0')}`,
      symbol: String(600000 + i),
      name: i === 0 ? '浦发银行' : `样例${String(i)}`,
    }));
    candidatePage.total = 30;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((input: RequestInfo | URL) => {
        const inputUrl =
          input instanceof Request ? input.url : input instanceof URL ? input.href : input;
        const path = new URL(inputUrl, 'http://localhost').pathname;
        const payload = path.endsWith('/candidates')
          ? candidatePage
          : path.includes('/candidates/')
            ? {
                ...baseCandidate,
                trade_date: run.trade_date,
                snapshot_data: { price: 10, pct_change: 4 },
                snapshot_evidence: {},
                rule_configuration: run.rule_configuration,
                intraday_analysis: null,
                web_research: null,
                workflow_state: null,
              }
            : responses[path];
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      }),
    );

    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <HashRouter>
          <Routes>
            <Route path="/tail-radar" element={<TailRadarPage />} />
            <Route path="/tail-radar/candidates/:candidateId" element={<CandidateDetailPage />} />
          </Routes>
        </HashRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('浦发银行')).toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText('5,000')).toBeInTheDocument();
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0);
    expect(screen.getAllByText('沪市主板').length).toBeGreaterThan(1);
    expect(screen.getByRole('link', { name: '600000' })).toHaveAttribute(
      'href',
      '#/tail-radar/candidates/55555555-5555-4555-8555-000000000000',
    );
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    fireEvent.click(screen.getByRole('link', { name: '600025' }));
    fireEvent.click(await screen.findByRole('link', { name: '返回尾盘雷达' }));
    expect(await screen.findByRole('link', { name: '600025' })).toBeInTheDocument();
    expect(screen.getByText('第 2 页，共 2 页')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('上市板块'), { target: { value: 'star' } });
    expect(screen.queryByRole('link', { name: '600000' })).not.toBeInTheDocument();
    expect(screen.getByText('没有符合当前条件的候选标的')).toBeInTheDocument();
  });
});
