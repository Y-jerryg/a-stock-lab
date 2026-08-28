import { cva, type VariantProps } from 'class-variance-authority';
import type { HTMLAttributes } from 'react';

import { cn } from '../../lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase',
  {
    variants: {
      variant: {
        neutral: 'border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)]',
        ready: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-600',
        reserved: 'border-slate-500/20 bg-slate-500/8 text-[var(--text-muted)]',
        warning: 'border-amber-500/25 bg-amber-500/10 text-amber-600',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
