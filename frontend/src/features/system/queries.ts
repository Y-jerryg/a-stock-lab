import { queryOptions } from '@tanstack/react-query';

import { getHealth } from './api';

export const healthQuery = queryOptions({
  queryKey: ['system', 'health'],
  queryFn: getHealth,
  refetchInterval: 60_000,
});
