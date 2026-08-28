import { ArrowRight, Bot, ChartNoAxesCombined, Radar, ScanSearch } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Badge } from '../../components/ui/badge';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { PageHeader } from '../../components/PageHeader';

const modules = [
  {
    title: 'Tail Radar',
    description: 'Point-in-time late-session A-share research workflow.',
    status: 'Foundation ready',
    badge: 'ready' as const,
    path: '/tail-radar',
    icon: Radar,
  },
  {
    title: 'Intelligence',
    description: 'Daily market, company, industry, policy, and macro intelligence.',
    status: 'Reserved',
    badge: 'reserved' as const,
    path: '/intelligence',
    icon: ScanSearch,
  },
  {
    title: 'Quant Lab',
    description: 'Historical data, factors, backtests, and statistical evaluation.',
    status: 'Reserved',
    badge: 'reserved' as const,
    path: '/quant-lab',
    icon: ChartNoAxesCombined,
  },
  {
    title: 'AI Research Assistant',
    description: 'Research assistant grounded in artifacts produced by this platform.',
    status: 'Reserved',
    badge: 'reserved' as const,
    path: '/assistant',
    icon: Bot,
  },
];

export function OverviewPage() {
  return (
    <div>
      <PageHeader
        eyebrow="System overview"
        title="Research workspace"
        description="A durable foundation for deterministic market research, structured intelligence, quantitative analysis, and artifact-grounded AI assistance."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {modules.map((module) => {
          const Icon = module.icon;
          return (
            <Card
              key={module.title}
              className="group transition-colors hover:border-[var(--border-strong)]"
            >
              <CardContent className="flex h-full min-h-52 flex-col">
                <div className="flex items-start justify-between">
                  <div className="grid size-9 place-items-center rounded-md bg-[var(--surface-muted)]">
                    <Icon className="size-4 text-[var(--accent)]" />
                  </div>
                  <Badge variant={module.badge}>{module.status}</Badge>
                </div>
                <h2 className="mt-5 text-base font-semibold">{module.title}</h2>
                <p className="mt-2 flex-1 text-sm leading-6 text-[var(--text-muted)]">
                  {module.description}
                </p>
                <Link
                  to={module.path}
                  className="mt-5 inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--accent)]"
                >
                  Open module
                  <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="mt-6">
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Foundation principles</h2>
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                System-wide research invariants
              </p>
            </div>
            <Badge>Phase 0</Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-px overflow-hidden rounded-md border border-[var(--border)] bg-[var(--border)] p-0 sm:grid-cols-3">
          {[
            [
              'Point-in-time integrity',
              'Historical work preserves an explicit, timezone-aware as-of boundary.',
            ],
            [
              'Deterministic first',
              'Market logic remains inspectable and separate from AI interpretation.',
            ],
            [
              'Shared artifacts',
              'Modules publish versioned structured research for downstream use.',
            ],
          ].map(([title, description]) => (
            <div key={title} className="bg-[var(--surface)] p-5">
              <p className="text-xs font-semibold">{title}</p>
              <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">{description}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
