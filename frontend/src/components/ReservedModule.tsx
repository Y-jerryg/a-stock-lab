import { LockKeyhole, type LucideIcon } from 'lucide-react';

import { Badge } from './ui/badge';
import { Card, CardContent } from './ui/card';
import { PageHeader } from './PageHeader';

interface ReservedModuleProps {
  title: string;
  eyebrow: string;
  description: string;
  purpose: string;
  icon: LucideIcon;
}

export function ReservedModule({
  title,
  eyebrow,
  description,
  purpose,
  icon: Icon,
}: ReservedModuleProps) {
  return (
    <div>
      <PageHeader eyebrow={eyebrow} title={title} description={description} />
      <Card>
        <CardContent className="grid min-h-80 place-items-center px-6 py-14 text-center">
          <div className="max-w-lg">
            <div className="mx-auto mb-5 grid size-12 place-items-center rounded-lg border border-[var(--border-strong)] bg-[var(--surface-muted)]">
              <Icon className="size-5 text-[var(--accent)]" />
            </div>
            <Badge variant="reserved">
              <LockKeyhole className="mr-1 size-3" /> 预留模块
            </Badge>
            <h2 className="mt-4 text-lg font-semibold">架构边界已建立</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{purpose}</p>
            <p className="mt-5 text-xs text-[var(--text-subtle)]">
              此处不会展示模拟数据或占位分析。
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
