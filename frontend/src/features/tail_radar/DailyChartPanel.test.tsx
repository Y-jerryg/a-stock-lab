import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { DailyChartPanel } from './DailyChartPanel';
vi.mock('../../components/DailyCandlestickChart', () => ({
  DailyCandlestickChart: () => <div role="img" aria-label="日 K 和成交量" />,
}));
afterEach(() => vi.unstubAllGlobals());
it('loads daily candles independently, displays the cutoff, and recovers after a provider failure', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response('{}', { status: 503 }))
    .mockResolvedValue(
      new Response(
        JSON.stringify({
          symbol: '600000',
          cutoff: '2026-09-16',
          fetched_at: '2026-09-17T10:00:00Z',
          bars: [
            {
              trade_date: '2026-09-16',
              open: 10,
              high: 11,
              low: 9,
              close: 10.5,
              volume: 12345,
              amount: 12345000,
            },
          ],
        }),
        { status: 200 },
      ),
    );
  vi.stubGlobal('fetch', fetcher);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DailyChartPanel candidateId="test" symbol="600000" />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByRole('button', { name: '重新加载日 K' }));
  expect(await screen.findByRole('img', { name: '日 K 和成交量' })).toBeInTheDocument();
  expect(screen.getByText(/行情截止 2026-09-16/)).toBeInTheDocument();
  expect(screen.getByText(/不参与原快照筛选或 AI 证据计算/)).toBeInTheDocument();
});
