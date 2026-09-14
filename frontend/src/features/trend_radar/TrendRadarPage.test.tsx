import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TrendRadarPage } from './TrendRadarPage';
import { marketTime } from './format';
import type { Result, Run } from './api';

const mocks = vi.hoisted(() => ({
  dashboard: vi.fn(),
  results: vi.fn(),
}));
vi.mock('./api', () => ({
  readDashboard: mocks.dashboard,
  readResults: mocks.results,
}));

const run: Run = {
  id: 'run-1',
  trade_date: '2026-09-11',
  status: 'success',
  started_at: '2026-09-11T07:45:00Z',
  finished_at: '2026-09-11T08:00:00Z',
  trigger_type: 'scheduled',
  payload: {
    data_as_of: '2026-09-11T08:00:00Z',
    heat_universe_count: 300,
    candidate_count: 1,
    strong_contraction_count: 1,
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
};
const stock: Result = {
  symbol: '600000',
  name: '示例股票',
  heat_rank: 2,
  trend_days: 9,
  trend_start_date: '2026-09-01',
  trend_end_date: '2026-09-11',
  trend_return_pct: -9,
  trend_slope: -1,
  pullback_days: 2,
  max_pullback_pct: 1.1,
  volume_ratio: 0.5,
  amount_ratio: 0.6,
  trend_volume_avg: 50,
  baseline_volume_avg: 100,
  trend_amount_avg: 60,
  baseline_amount_avg: 100,
  is_strong_volume_contraction: true,
  highlight_level: 'strong',
};

function mount(component: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter>{component}</MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.dashboard.mockResolvedValue({ latest: run, attempts: [run], workers: [] });
  mocks.results.mockResolvedValue([stock]);
});
describe('Trend Radar', () => {
  it('keeps the last successful dataset when the latest scan fails, with Chinese labels', async () => {
    mocks.dashboard.mockResolvedValue({
      latest: run,
      attempts: [{ ...run, id: 'failed', status: 'failed' }, run],
      workers: [],
    });
    mount(<TrendRadarPage />);
    expect(await screen.findByText('示例股票')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '示例股票' })).toHaveAttribute(
      'href',
      '/trend-radar/runs/run-1/stocks/600000',
    );
    expect(screen.getByText('最近一次扫描失败，当前仍展示最近一次成功结果。')).toBeInTheDocument();
    expect(screen.getByText('9日下降趋势')).toBeInTheDocument();
    expect(screen.queryByText('strong')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('趋势天数'), { target: { value: '7' } });
    expect(screen.getByText('当前扫描未发现符合条件的股票。')).toBeInTheDocument();
  });
  it('offers only read-only result filters and no login or scan control', async () => {
    mount(<TrendRadarPage />);
    expect(await screen.findByText('示例股票')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '扫描控制' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('邮箱')).not.toBeInTheDocument();
  });
  it('shows an empty result state before the first publication', async () => {
    mocks.dashboard.mockResolvedValue({ latest: null, attempts: [] });
    mount(<TrendRadarPage />);
    expect(await screen.findByText('当前没有可展示的成功扫描结果。')).toBeInTheDocument();
    expect(mocks.results).not.toHaveBeenCalled();
  });
  it('uses Shanghai time', () => {
    expect(marketTime('2026-09-11T07:45:00Z')).toContain('15:45');
  });
  it('shows partial results, coverage and failed stocks', async () => {
    const partial: Run = {
      ...run,
      status: 'completed_with_warnings',
      payload: {
        ...run.payload,
        requested_count: 300,
        successful_count: 297,
        failed_count: 3,
        failed_symbols: [{ symbol: '600519', name: '贵州茅台', error_code: 'provider_error' }],
      },
    };
    mocks.dashboard.mockResolvedValue({ latest: partial, attempts: [partial] });
    mount(<TrendRadarPage />);
    expect(await screen.findByText('示例股票')).toBeInTheDocument();
    expect(screen.getByText('请求 300 只 · 成功处理 297 只 · 失败 3 只')).toBeInTheDocument();
    expect(screen.getByText(/600519 贵州茅台/)).toBeInTheDocument();
    expect(screen.getByText(/扫描已完成，部分股票数据获取失败/)).toBeInTheDocument();
  });
  it('does not claim previous results exist after the first failed scan', async () => {
    mocks.dashboard.mockResolvedValue({ latest: null, attempts: [{ ...run, status: 'failed' }] });
    mount(<TrendRadarPage />);
    expect(await screen.findByText('最近一次扫描失败，尚无可展示的完整结果。')).toBeInTheDocument();
    expect(
      screen.queryByText('最近一次扫描失败，当前仍展示最近一次成功结果。'),
    ).not.toBeInTheDocument();
  });
});
