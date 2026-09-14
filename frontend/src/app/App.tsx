import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from './AppShell';
import { text } from '../locales';
import { AssistantPage } from '../features/assistant/AssistantPage';
import { IntelligencePage } from '../features/intelligence/IntelligencePage';
import { OverviewPage } from '../features/overview/OverviewPage';
import { QuantLabPage } from '../features/quant_lab/QuantLabPage';
import { DataStatusPage } from '../features/system/DataStatusPage';
import { TailRadarPage } from '../features/tail_radar/TailRadarPage';
import { ApiError } from '../lib/api/client';

const CandidateDetailPage = lazy(async () => {
  const module = await import('../features/tail_radar/CandidateDetailPage');
  return { default: module.CandidateDetailPage };
});

const TrendRadarPage = lazy(async () => {
  const module = await import('../features/trend_radar/TrendRadarPage');
  return { default: module.TrendRadarPage };
});
const TrendStockDetailPage = lazy(async () => {
  const module = await import('../features/trend_radar/TrendStockDetailPage');
  return { default: module.TrendStockDetailPage };
});
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status === 404) && failureCount < 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<OverviewPage />} />
            <Route path="tail-radar" element={<TailRadarPage />} />
            <Route
              path="trend-radar"
              element={
                <Suspense fallback={<p role="status">{text.trend.loading}</p>}>
                  <TrendRadarPage />
                </Suspense>
              }
            />
            <Route path="trend-radar/admin" element={<Navigate to="/trend-radar" replace />} />
            <Route
              path="trend-radar/runs/:runId/stocks/:symbol"
              element={
                <Suspense fallback={<p role="status">正在加载股票日线详情……</p>}>
                  <TrendStockDetailPage />
                </Suspense>
              }
            />
            <Route
              path="tail-radar/candidates/:candidateId"
              element={
                <Suspense
                  fallback={
                    <div className="animate-pulse rounded-lg border border-[var(--border)] bg-[var(--surface)] p-6 text-sm text-[var(--text-muted)]">
                      正在加载候选标的研究结果……
                    </div>
                  }
                >
                  <CandidateDetailPage />
                </Suspense>
              }
            />
            <Route path="intelligence" element={<IntelligencePage />} />
            <Route path="quant-lab" element={<QuantLabPage />} />
            <Route path="assistant" element={<AssistantPage />} />
            <Route path="data-status" element={<DataStatusPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </HashRouter>
    </QueryClientProvider>
  );
}
