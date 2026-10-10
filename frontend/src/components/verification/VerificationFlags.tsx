import { AlertTriangle, AlertCircle, Info, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { VerificationFlag } from '@/types';
import { cn, severityConfig } from '@/lib/utils';

interface VerificationFlagsProps {
  flags: VerificationFlag[];
  onDismiss?: (flag: VerificationFlag) => void;
}

const LAYER_LABELS: Record<VerificationFlag['layer'], string> = {
  DOCUMENT:     'Document',
  IMAGE:        'Image',
  GEOSPATIAL:   'Geospatial',
  MASS_BALANCE: 'Mass Balance',
  DUPLICATE:    'Duplicate',
  GRAPH:        'Graph',
  ML:           'ML Signal',
};

const SEVERITY_ICONS = {
  CRITICAL: AlertTriangle,
  WARNING:  AlertCircle,
  INFO:     Info,
};

const verificationFlagKey = (flag: VerificationFlag) =>
  flag.flag_id ?? `${flag.code}:${(flag.related_claim_ids ?? []).join(',')}:${flag.evidence_ids.join(',')}`;

export function VerificationFlags({ flags, onDismiss }: VerificationFlagsProps) {
  const [expanded, setExpanded] = useState<string | null>(() =>
    flags[0] ? verificationFlagKey(flags[0]) : null
  );

  if (flags.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-8 text-center">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50">
          <Info className="h-5 w-5 text-emerald-600" aria-hidden="true" />
        </div>
        <p className="text-sm font-medium text-slate-700">No flags raised</p>
        <p className="text-xs text-slate-500">All verification layers passed without issues.</p>
      </div>
    );
  }

  const sorted = [...flags].sort((a, b) => {
    const lifecycle = { ACTIVE: 0, RESOLVED: 1, DISMISSED: 2 };
    const order = { CRITICAL: 0, WARNING: 1, INFO: 2 };
    return lifecycle[a.status ?? 'ACTIVE'] - lifecycle[b.status ?? 'ACTIVE']
      || order[a.severity] - order[b.severity]
      || (b.risk_contribution ?? 0) - (a.risk_contribution ?? 0);
  });

  return (
    <ol className="space-y-2" aria-label="Verification flags">
      {sorted.map((flag) => {
        const sev = severityConfig(flag.severity);
        const Icon = SEVERITY_ICONS[flag.severity];
        const flagKey = verificationFlagKey(flag);
        const isOpen = expanded === flagKey;

        return (
          <li
            key={flagKey}
            className={cn(
              'rounded-lg border border-l-[3px] overflow-hidden',
              sev.bg,
              sev.border
            )}
          >
            <button
              type="button"
              className="flex w-full items-start gap-3 p-3 text-left"
              onClick={() => setExpanded(isOpen ? null : flagKey)}
              aria-expanded={isOpen}
            >
              <Icon
                className={cn('mt-0.5 h-4 w-4 shrink-0', sev.icon)}
                aria-hidden="true"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={cn('text-xs font-semibold uppercase tracking-wide', sev.text)}>
                    {flag.severity}
                  </span>
                  <span className="text-xs text-slate-400">·</span>
                  <span className="text-xs text-slate-500">{LAYER_LABELS[flag.layer]}</span>
                  {flag.rule_reference && (
                    <>
                      <span className="text-xs text-slate-400">·</span>
                      <span className="font-mono text-[10px] text-slate-400">{flag.rule_reference}</span>
                    </>
                  )}
                </div>
                <p className={cn('mt-0.5 text-sm font-medium', sev.text)}>
                  {flag.rule_name || flag.description}
                </p>
                <p className="mt-0.5 text-xs text-slate-600">{flag.description}</p>
              </div>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${flag.status === 'RESOLVED' ? 'bg-slate-100 text-slate-600' : flag.status === 'DISMISSED' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>{flag.status || 'ACTIVE'}</span>
              <span className="shrink-0 text-slate-400">
                {isOpen
                  ? <ChevronUp className="h-4 w-4" aria-hidden="true" />
                  : <ChevronDown className="h-4 w-4" aria-hidden="true" />
                }
              </span>
            </button>

            {isOpen && (
              <div className="border-t border-slate-200/60 px-3 py-2 bg-white/50">
                {flag.rationale && <p className="mb-2 text-[11px] text-slate-600"><strong>Why this rule exists: </strong>{flag.rationale}</p>}
                {flag.recommended_action && <p className="mb-2 text-[11px] text-teal-800"><strong>Suggested review: </strong>{flag.recommended_action}</p>}
                {flag.resolution_reason && <p className="mb-2 text-[11px] text-slate-500"><strong>Resolution: </strong>{flag.resolution_reason}</p>}
                {flag.flag_id && flag.status !== 'RESOLVED' && flag.status !== 'DISMISSED' && onDismiss && <button type="button" className="mb-2 rounded border border-slate-300 bg-white px-2.5 py-1.5 text-[11px] font-medium text-slate-700 hover:bg-slate-50" onClick={() => onDismiss(flag)}>Dismiss finding with reason</button>}
                {Object.keys(flag.actual_values ?? {}).length > 0 && (
                  <div className="mb-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Actual values</p>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(flag.actual_values ?? {}).map(([key, value]) => (
                        <span key={key} className="rounded bg-white border border-slate-200 px-2 py-0.5 text-[10px] text-slate-600">
                          {key.replace(/_/g, ' ')}: {value === null ? 'missing' : value}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {flag.expected_relationship && (
                  <p className="mb-1 text-[11px] text-slate-600">
                    <span className="font-semibold">Expected: </span>{flag.expected_relationship}
                  </p>
                )}
                {flag.related_claim_ids?.length ? (
                  <div className="mb-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Related claims</p>
                    <div className="flex flex-wrap gap-1.5">
                      {flag.related_claim_ids.map(id => (
                        <Link key={id} to={`/gov/claims/${id}`} className="rounded bg-white border border-slate-200 px-2 py-0.5 font-mono text-[10px] text-indigo-700 hover:underline">{id}</Link>
                      ))}
                    </div>
                  </div>
                ) : null}
                {flag.matched_fields?.length ? (
                  <p className="mb-2 text-[11px] text-slate-600">
                    <span className="font-semibold">Matching fields: </span>{flag.matched_fields.join(', ')}
                  </p>
                ) : null}
                {(flag.difference_kg != null || flag.variance_pct != null) && (
                  <p className="mb-1 text-[11px] text-slate-600">
                    <span className="font-semibold">Difference: </span>
                    {flag.difference_kg == null ? '—' : `${flag.difference_kg.toFixed(1)} kg`}
                    {flag.variance_pct == null ? '' : ` (${flag.variance_pct.toFixed(1)}%)`}
                  </p>
                )}
                {flag.risk_contribution != null && (
                  <p className="mb-2 text-[11px] font-semibold text-red-700">Risk contribution: +{flag.risk_contribution}</p>
                )}
                {flag.evidence_ids.length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1.5">Evidence References</p>
                    <div className="flex flex-wrap gap-1.5">
                      {flag.evidence_ids.map((id) => (
                          <Link
                          key={id}
                            to={`#evidence-${id}`}
                            className="inline-flex items-center rounded bg-white border border-slate-200 px-2 py-0.5 font-mono text-[10px] text-indigo-700 hover:underline"
                        >
                          {id}
                          </Link>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
