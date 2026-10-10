import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  icon: LucideIcon;
  trend?: { value: number; label: string };
  accent?: 'default' | 'teal' | 'amber' | 'red' | 'emerald';
}

const ACCENT_MAP = {
  default: { icon: 'text-slate-500', bg: 'bg-slate-100' },
  teal:    { icon: 'text-teal-600',  bg: 'bg-teal-50'  },
  amber:   { icon: 'text-amber-600', bg: 'bg-amber-50' },
  red:     { icon: 'text-red-600',   bg: 'bg-red-50'   },
  emerald: { icon: 'text-emerald-600', bg: 'bg-emerald-50' },
};

export function StatCard({
  label,
  value,
  subtext,
  icon: Icon,
  trend,
  accent = 'default',
}: StatCardProps) {
  const colors = ACCENT_MAP[accent];

  return (
    <article className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
        <span className={cn('flex h-8 w-8 items-center justify-center rounded-lg', colors.bg)}>
          <Icon className={cn('h-4 w-4', colors.icon)} aria-hidden="true" />
        </span>
      </div>
      <div>
        <p className="text-2xl font-bold text-slate-900 tabular-nums">{value}</p>
        {subtext && <p className="mt-0.5 text-xs text-slate-500">{subtext}</p>}
      </div>
      {trend && (
        <p
          className={cn(
            'text-xs font-medium',
            trend.value >= 0 ? 'text-emerald-600' : 'text-red-600'
          )}
        >
          {trend.value >= 0 ? '↑' : '↓'} {Math.abs(trend.value)}% {trend.label}
        </p>
      )}
    </article>
  );
}
