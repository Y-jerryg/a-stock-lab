import { Clock3, Radar, ShieldCheck } from 'lucide-react';

import { Badge } from '../../components/ui/badge';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { PageHeader } from '../../components/PageHeader';

export function TailRadarPage() {
  return (
    <div>
      <PageHeader
        eyebrow="Research / Tail Radar"
        title="Tail Radar"
        description="A future point-in-time late-session research workflow for the full A-share market. Phase 0 establishes its durable boundaries without implementing market logic."
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardContent className="grid min-h-[420px] place-items-center px-6 py-16 text-center">
            <div className="max-w-lg">
              <div className="mx-auto mb-5 grid size-14 place-items-center rounded-xl border border-[var(--border-strong)] bg-[var(--surface-muted)] shadow-sm">
                <Radar className="size-6 text-[var(--accent)]" />
              </div>
              <Badge variant="ready">Foundation ready</Badge>
              <h2 className="mt-4 text-xl font-semibold tracking-tight">
                No research run has been produced
              </h2>
              <p className="mt-3 text-sm leading-6 text-[var(--text-muted)]">
                Market providers, trading-calendar rules, snapshot capture, candidate selection, and
                analysis are intentionally deferred. Results will appear here only when backed by a
                persisted research artifact.
              </p>
              <div className="mx-auto mt-7 flex max-w-sm items-start gap-3 rounded-md border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-left">
                <ShieldCheck className="mt-0.5 size-4 shrink-0 text-[var(--text-subtle)]" />
                <p className="text-xs leading-5 text-[var(--text-muted)]">
                  Expensive research execution will be an authenticated internal operation, not an
                  anonymous public action.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold">Workflow contract</h2>
          </CardHeader>
          <CardContent>
            <dl className="space-y-5 text-sm">
              <div>
                <dt className="text-[11px] font-semibold tracking-wide text-[var(--text-subtle)] uppercase">
                  Evaluation model
                </dt>
                <dd className="mt-1.5 text-[var(--text-muted)]">
                  Single point-in-time market snapshot
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold tracking-wide text-[var(--text-subtle)] uppercase">
                  Canonical timezone
                </dt>
                <dd className="mt-1.5 flex items-center gap-2 text-[var(--text-muted)]">
                  <Clock3 className="size-3.5" /> Asia/Shanghai
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold tracking-wide text-[var(--text-subtle)] uppercase">
                  Output contract
                </dt>
                <dd className="mt-1.5 text-[var(--text-muted)]">
                  Versioned ResearchArtifact records
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold tracking-wide text-[var(--text-subtle)] uppercase">
                  Current phase
                </dt>
                <dd className="mt-1.5 text-[var(--text-muted)]">
                  Architecture only · no market data
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
