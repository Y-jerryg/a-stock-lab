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
        eyebrow="系统"
        title="数据状态"
        description="查看后端和数据库的实时连接状态。市场快照与分析数据只由内部任务生成，公共网页不会触发采集或付费分析。"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void health.refetch()}
            disabled={health.isFetching}
          >
            <RefreshCw className={health.isFetching ? 'size-3.5 animate-spin' : 'size-3.5'} />
            刷新
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="size-4 text-[var(--accent)]" />
                <h2 className="text-sm font-semibold">后端接口</h2>
              </div>
              {health.isSuccess && (
                <Badge variant={health.data.status === 'ok' ? 'ready' : 'warning'}>
                  {health.data.status === 'ok' ? '正常' : '异常'}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {health.isPending && (
              <p className="text-sm text-[var(--text-muted)]">正在检查后端连接……</p>
            )}
            {health.isError && (
              <div className="flex gap-3 text-sm text-[var(--text-muted)]">
                <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
                <div>
                  <p className="font-medium text-[var(--text-primary)]">后端不可用</p>
                  <p className="mt-1 text-xs leading-5">请启动后端服务，并检查公共接口地址配置。</p>
                </div>
              </div>
            )}
            {health.isSuccess && (
              <dl className="grid grid-cols-[120px_1fr] gap-x-4 gap-y-3 text-xs">
                <dt className="text-[var(--text-subtle)]">服务</dt>
                <dd className="font-mono text-[var(--text-muted)]">{health.data.service}</dd>
                <dt className="text-[var(--text-subtle)]">版本</dt>
                <dd className="font-mono text-[var(--text-muted)]">{health.data.version}</dd>
                <dt className="text-[var(--text-subtle)]">数据库</dt>
                <dd className="font-medium text-[var(--text-muted)]">
                  {health.data.database.status === 'available' ? '可用' : '不可用'}
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
                <h2 className="text-sm font-semibold">市场数据集</h2>
              </div>
              <Badge variant="ready">运行时持久化</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-[var(--text-muted)]">
              全市场快照与日内分析数据由内部工作流写入 PostgreSQL 和 Parquet 运行时目录。
              运行时金融数据不会提交到 Git；本页面只展示状态，不会执行实时扫描。
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
