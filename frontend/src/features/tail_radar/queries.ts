import { queryOptions } from '@tanstack/react-query';

import { getAllCandidates, getCandidate, getLatestRun, getRunSummary } from './api';

export const latestTailRadarRunQuery = queryOptions({
  queryKey: ['tail-radar', 'runs', 'latest'],
  queryFn: getLatestRun,
});

export function tailRadarRunSummaryQuery(runId: string) {
  return queryOptions({
    queryKey: ['tail-radar', 'runs', runId, 'summary'],
    queryFn: () => getRunSummary(runId),
  });
}

export function tailRadarCandidatesQuery(runId: string) {
  return queryOptions({
    queryKey: ['tail-radar', 'runs', runId, 'candidates'],
    queryFn: () => getAllCandidates(runId),
  });
}

export function tailRadarCandidateQuery(candidateId: string) {
  return queryOptions({
    queryKey: ['tail-radar', 'candidates', candidateId],
    queryFn: () => getCandidate(candidateId),
  });
}
