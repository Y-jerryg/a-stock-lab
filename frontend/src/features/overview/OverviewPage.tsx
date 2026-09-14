import { ArrowRight, Bot, ChartNoAxesCombined, Radar, ScanSearch } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Badge } from '../../components/ui/badge';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { PageHeader } from '../../components/PageHeader';

const modules = [
  {
    title: '尾盘雷达',
    description: '面向A股尾盘时点的完整研究工作流。',
    status: '功能就绪',
    badge: 'ready' as const,
    path: '/tail-radar',
    icon: Radar,
  },
  {
    title: '情报中心',
    description: '汇总市场、公司、行业、政策和宏观层面的每日情报。',
    status: '暂未开放',
    badge: 'reserved' as const,
    path: '/intelligence',
    icon: ScanSearch,
  },
  {
    title: '量化实验室',
    description: '用于历史数据、因子、回测和统计评估。',
    status: '暂未开放',
    badge: 'reserved' as const,
    path: '/quant-lab',
    icon: ChartNoAxesCombined,
  },
  {
    title: 'AI 研究助手',
    description: '基于本平台研究成果提供辅助分析。',
    status: '暂未开放',
    badge: 'reserved' as const,
    path: '/assistant',
    icon: Bot,
  },
];

export function OverviewPage() {
  return (
    <div>
      <PageHeader
        eyebrow="系统总览"
        title="研究工作台"
        description="为确定性市场研究、结构化情报、量化分析和基于研究成果的 AI 辅助建立可持续演进的基础。"
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
                  打开模块
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
              <h2 className="text-sm font-semibold">基础原则</h2>
              <p className="mt-1 text-xs text-[var(--text-muted)]">全系统必须遵守的研究约束</p>
            </div>
            <Badge>基础阶段</Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-px overflow-hidden rounded-md border border-[var(--border)] bg-[var(--border)] p-0 sm:grid-cols-3">
          {[
            ['时点完整性', '历史研究必须保留明确、带时区的资料截止时点。'],
            ['确定性优先', '市场规则保持可检查，并与 AI 解释严格分离。'],
            ['共享研究成果', '各模块发布带版本的结构化研究成果，供后续功能复用。'],
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
