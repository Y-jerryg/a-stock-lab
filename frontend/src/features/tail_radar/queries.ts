import { queryOptions } from '@tanstack/react-query';

import {
  getAllCandidates,
  getCandidate,
  getLatestRun,
  getResearchAvailability,
  getRunSummary,
} from './api';

export const latestTailRadarRunQuery = queryOptions({
  queryKey: ['tail-radar', 'runs', 'latest'],
  queryFn: getLatestRun,
});

export function tailRadarRunSummaryQuery(runId: string) {
  return queryOptions({
    queryKey: ['tail-radar', 'runs', runId, 'summary'],
    queryFn: () => getRunSummary(runId),
    refetchInterval: (query) =>
      query.state.data?.workflow?.execution_status === 'running' ? 5_000 : false,
  });
}

export function tailRadarCandidatesQuery(runId: string) {
  return queryOptions({
    queryKey: ['tail-radar', 'runs', runId, 'candidates'],
    queryFn: () => getAllCandidates(runId),
    refetchInterval: (query) =>
      query.state.data?.some((item) => ['pending', 'running'].includes(item.technical_status ?? ''))
        ? 5_000
        : false,
  });
}

export function tailRadarCandidateQuery(candidateId: string) {
  return queryOptions({
    queryKey: ['tail-radar', 'candidates', candidateId],
    queryFn: () => getCandidate(candidateId),
    refetchInterval: (query) => {
      const state = query.state.data?.workflow_state;
      return state &&
        (['pending', 'running'].includes(state.technical_status) ||
          state.research_status === 'running')
        ? 5_000
        : false;
    },
  });
}

export const tailRadarResearchAvailabilityQuery = queryOptions({
  queryKey: ['tail-radar', 'research-availability'],
  queryFn: getResearchAvailability,
  staleTime: 60_000,
});
