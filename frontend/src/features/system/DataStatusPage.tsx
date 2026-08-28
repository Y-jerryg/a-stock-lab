import { useQuery } from '@tanstack/react-query';
import { CircleAlert, Database, RefreshCw, Server } from 'lucide-react';

import { PageHeader } from '../../components/PageHeader';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { healthQuery } from './queries';

export function DataStatusPage() {
  const health = useQuery(healthQuery);

  return (
    <div>
      <PageHeader
        eyebrow="System"
        title="Data Status"
        description="Live connectivity for foundation services. Market datasets and provider feeds are not configured in Phase 0."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void health.refetch()}
            disabled={health.isFetching}
          >
            <RefreshCw className={health.isFetching ? 'size-3.5 animate-spin' : 'size-3.5'} />
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="size-4 text-[var(--accent)]" />
                <h2 className="text-sm font-semibold">Backend API</h2>
              </div>
              {health.isSuccess && (
                <Badge variant={health.data.status === 'ok' ? 'ready' : 'warning'}>
                  {health.data.status}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {health.isPending && (
              <p className="text-sm text-[var(--text-muted)]">Checking backend connection…</p>
            )}
            {health.isError && (
              <div className="flex gap-3 text-sm text-[var(--text-muted)]">
                <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
                <div>
                  <p className="font-medium text-[var(--text-primary)]">Backend unavailable</p>
                  <p className="mt-1 text-xs leading-5">
                    Start the API service and verify the public API base URL.
                  </p>
                </div>
              </div>
            )}
            {health.isSuccess && (
              <dl className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-3 text-xs">
                <dt className="text-[var(--text-subtle)]">Service</dt>
                <dd className="font-mono text-[var(--text-muted)]">{health.data.service}</dd>
                <dt className="text-[var(--text-subtle)]">Version</dt>
                <dd className="font-mono text-[var(--text-muted)]">{health.data.version}</dd>
                <dt className="text-[var(--text-subtle)]">Database</dt>
                <dd className="font-medium text-[var(--text-muted)]">
                  {health.data.database.status}
                </dd>
              </dl>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Database className="size-4 text-[var(--accent)]" />
                <h2 className="text-sm font-semibold">Market datasets</h2>
              </div>
              <Badge variant="reserved">Not configured</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-[var(--text-muted)]">
              Provider integrations, full-market snapshots, historical bars, and Parquet datasets
              are deliberately outside this phase. Runtime storage directories are reserved and
              excluded from version control.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
