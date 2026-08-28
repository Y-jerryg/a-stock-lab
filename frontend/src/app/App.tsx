import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from './AppShell';
import { AssistantPage } from '../features/assistant/AssistantPage';
import { IntelligencePage } from '../features/intelligence/IntelligencePage';
import { OverviewPage } from '../features/overview/OverviewPage';
import { QuantLabPage } from '../features/quant_lab/QuantLabPage';
import { DataStatusPage } from '../features/system/DataStatusPage';
import { TailRadarPage } from '../features/tail_radar/TailRadarPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
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
