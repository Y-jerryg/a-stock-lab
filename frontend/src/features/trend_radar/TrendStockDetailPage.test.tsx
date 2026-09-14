import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { readRunDetails, type RunDetails } from './api';
import { movingAverage } from './chartData';
import { TrendStockDetailPage } from './TrendStockDetailPage';

vi.mock('./DailyCandlestickChart', () => ({
  DailyCandlestickChart: ({ symbol }: { symbol: string }) => (
    <div role="img" aria-label={`${symbol} 前复权日 K 线、均线与成交量图`} />
  ),
}));
const runId = '11111111-1111-4111-8111-111111111111';
function fixture(): RunDetails {
  return {
    schema_version: 1,
    volume_unit: 'lot',
    amount_unit: 'CNY',
    run: {
      id: runId,
      trade_date: '2026-09-11',
      status: 'success',
      started_at: '2026-09-13T09:00:00Z',
      finished_at: '2026-09-13T09:01:00Z',
      trigger_type: 'cli',
      payload: {
        data_as_of: '2026-09-13T09:01:00Z',
        heat_universe_count: 300,
        candidate_count: 1,
        strong_contraction_count: 0,
        configuration_snapshot: {
          top_n: 300,
          min_days: 7,
          max_days: 9,
          max_pullback_days: 3,
          max_single_pullback_pct: 1.5,
          baseline_volume_days: 20,
          strong_volume_ratio: 0.55,
        },
      },
    },
    details: [
      {
        candidate: {
          symbol: '600000',
          name: '示例股票',
          heat_rank: 20,
          trend_days: 7,
          trend_start_date: '2026-09-10',
          trend_end_date: '2026-09-11',
          trend_return_pct: -5,
          trend_slope: -0.2,
          pullback_days: 1,
          max_pullback_pct: 0.6,
          trend_volume_avg: 800,
          baseline_volume_avg: 1000,
          volume_ratio: 0.8,
          trend_amount_avg: 760000,
          baseline_amount_avg: 1000000,
          amount_ratio: 0.76,
          is_strong_volume_contraction: false,
          highlight_level: 'normal',
        },
        bars: ['2026-09-10', '2026-09-11'].map((day, index) => ({
          symbol: '600000',
          trade_date: day,
          open: 10,
          high: 11,
          low: 9,
          close: 10 - index * 0.5,
          volume: 1000,
          amount: 950000,
          adjustment_type: 'qfq',
          source: 'sina_daily_qfq',
          fetched_at: '2026-09-13T09:00:30Z',
        })),
      },
    ],
  };
}
function respond(value: unknown, status = 200) {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(value), { status }));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
function mount(symbol = '600000') {
  vi.stubGlobal('scrollTo', vi.fn());
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/trend-radar/runs/${runId}/stocks/${symbol}`]}>
        <Routes>
          <Route
            path="/trend-radar/runs/:runId/stocks/:symbol"
            element={<TrendStockDetailPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());

describe('saved Trend Radar stock detail', () => {
  it('loads a direct link with saved bars, units, metrics and the same-run return link', async () => {
    const fetcher = respond(fixture());
    mount();
    expect(await screen.findByRole('heading', { name: /示例股票/ })).toBeInTheDocument();
    expect(await screen.findByRole('img', { name: /600000 前复权日 K 线/ })).toBeInTheDocument();
    expect(screen.getByText('未达到强缩量阈值')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /返回本次扫描结果/ })).toHaveAttribute(
      'href',
      `/trend-radar?run=${runId}`,
    );
    fireEvent.click(screen.getByText('查看每日行情数据（2 条）'));
    expect(screen.getByRole('columnheader', { name: '成交量（手）' })).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(
      `/data/trend-radar/details/${runId}.json`,
      expect.objectContaining({ method: 'GET', credentials: 'omit' }),
    );
  });
  it('explains re-export for an older bundle without fetching live quotes', async () => {
    const fetcher = respond(null, 404);
    mount();
    expect(await screen.findByText('此历史扫描尚未导出 K 线详情')).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('does not substitute another candidate for an unknown symbol', async () => {
    respond(fixture());
    mount('600001');
    expect(await screen.findByRole('alert')).toHaveTextContent('这只股票不在本次扫描的候选结果中');
  });
  it.each([
    'future_date',
    'future_knowledge',
    'wrong_symbol',
    'wrong_run',
    'duplicate',
    'invalid_price',
  ])('rejects %s evidence', async (problem) => {
    const value = fixture();
    const detail = value.details[0];
    const bar = detail?.bars[0];
    if (!detail || !bar) throw new Error('Missing test evidence');
    if (problem === 'future_date') bar.trade_date = '2026-09-14';
    if (problem === 'future_knowledge') bar.fetched_at = '2026-09-14T09:00:00Z';
    if (problem === 'wrong_symbol') bar.symbol = '600001';
    if (problem === 'wrong_run') value.run.id = '22222222-2222-4222-8222-222222222222';
    if (problem === 'duplicate') detail.bars.push(bar);
    if (problem === 'invalid_price') bar.low = 100;
    respond(value);
    await expect(readRunDetails(runId)).rejects.toThrow('invalid_run_details');
  });
  it('moving averages use only the available trailing observations', () => {
    const bars = fixture().details[0]?.bars;
    if (!bars) throw new Error('Missing test evidence');
    expect(movingAverage(bars, 2)).toEqual([null, 9.75]);
    expect(movingAverage(bars, 5)).toEqual([null, null]);
  });
});
