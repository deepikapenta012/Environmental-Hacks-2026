import type { ExplainabilityBreakdown as Breakdown, RuleContribution } from '@/types';
import { CheckCircle2, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  data: Breakdown;
}

const LAYER_SCORES: { key: keyof Omit<Breakdown, 'rule_contributions' | 'score_history'>; label: string }[] = [
  { key: 'document_score',     label: 'Document' },
  { key: 'image_score',        label: 'Image' },
  { key: 'geospatial_score',   label: 'Geospatial' },
  { key: 'mass_balance_score', label: 'Mass Balance' },
  { key: 'duplicate_score',    label: 'Duplicate' },
  { key: 'graph_score',        label: 'Graph' },
  { key: 'ml_anomaly_score',   label: 'ML Anomaly' },
];

function ScoreBar({ label, score }: { label: string; score: number | null }) {
  if (score === null) return <div className="flex items-center gap-3"><span className="w-24 shrink-0 text-xs text-slate-500 text-right">{label}</span><span className="text-xs text-slate-400">Unavailable</span></div>;
  const pct = Math.min(100, score * 3.33); // max 30 points per layer → 100%
  const color =
    score >= 20
      ? 'bg-red-500'
      : score >= 10
      ? 'bg-orange-400'
      : score >= 5
      ? 'bg-amber-400'
      : 'bg-emerald-500';

  return (
    <div className="flex items-center gap-3">
      <span className="w-24 shrink-0 text-xs text-slate-500 text-right">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-700', color)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={0}
          aria-valuemax={30}
        />
      </div>
      <span className="w-7 text-right text-xs font-mono font-medium text-slate-700">
        {score}
      </span>
    </div>
  );
}

function RuleRow({ rule }: { rule: RuleContribution }) {
  return (
    <li className="flex items-start gap-2.5 py-2 border-b border-slate-100 last:border-0">
      {rule.triggered ? (
        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" aria-hidden="true" />
      ) : (
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" aria-hidden="true" />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium text-slate-700">{rule.label}</span>
          <span
            className={cn(
              'text-xs font-mono font-semibold tabular-nums',
              rule.triggered ? 'text-red-600' : 'text-slate-400'
            )}
          >
            {rule.triggered ? `+${rule.score_delta}` : '0'}
          </span>
        </div>
        <p className="text-[11px] text-slate-400">{rule.details}</p>
      </div>
    </li>
  );
}

export function ExplainabilityBreakdown({ data }: Props) {
  return (
    <section aria-label="Explainability breakdown" className="space-y-5">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-3">
          Score by Verification Layer
        </h4>
        <div className="space-y-2">
          {LAYER_SCORES.filter(({ key }) => data[key] !== undefined).map(({ key, label }) => (
            <ScoreBar key={key} label={label} score={data[key]} />
          ))}
        </div>
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
          Rule Contributions
        </h4>
        <ul className="divide-y divide-slate-100">
          {data.rule_contributions.map((rule) => (
            <RuleRow key={rule.rule_id} rule={rule} />
          ))}
        </ul>
      </div>
    </section>
  );
}
