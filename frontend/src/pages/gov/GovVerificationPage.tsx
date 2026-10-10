import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldCheck, ShieldAlert, Clock, ArrowUpRight, CheckCircle2, XCircle } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { RiskScore } from '@/components/ui/RiskScore';
import { fetchClaims } from '@/lib/api';
import { claimStatusConfig, formatDate, formatWeight } from '@/lib/utils';
import type { RecyclingClaim } from '@/types';

export function GovVerificationPage() {
  const [claims, setClaims]   = useState<RecyclingClaim[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchClaims().then(r => setClaims(r.data)).finally(() => setLoading(false));
  }, []);

  const pending  = claims.filter(c => c.status === 'PENDING' || c.status === 'FLAGGED');
  const verified = claims.filter(c => c.status === 'VERIFIED' || c.status === 'APPROVED');
  const rejected = claims.filter(c => c.status === 'REJECTED');
  const flagged  = claims.filter(c => c.status === 'FLAGGED');

  return (
    <div className="flex flex-col min-h-full">
      <TopBar
        title="Verification Queue"
        subtitle="Review pending claims and issue decisions"
      />
      <div className="flex-1 p-6 space-y-6 animate-fade-in">

        {/* Summary cards */}
        <section className="grid grid-cols-2 gap-4 sm:grid-cols-4" aria-label="Verification summary">
          {[
            { label: 'Awaiting Decision', count: pending.length,  icon: Clock,        bg: 'bg-amber-50',   text: 'text-amber-600'  },
            { label: 'Verified',          count: verified.length, icon: CheckCircle2, bg: 'bg-emerald-50', text: 'text-emerald-600'},
            { label: 'Rejected',          count: rejected.length, icon: XCircle,      bg: 'bg-red-50',     text: 'text-red-600'    },
            { label: 'Flagged by AI',     count: flagged.length,  icon: ShieldAlert,  bg: 'bg-orange-50',  text: 'text-orange-600' },
          ].map(({ label, count, icon: Icon, bg, text }) => (
            <Card key={label} className="flex items-center gap-3">
              <div className={`h-10 w-10 rounded-lg flex items-center justify-center shrink-0 ${bg}`}>
                <Icon className={`h-5 w-5 ${text}`} aria-hidden="true" />
              </div>
              <div>
                <p className="text-xl font-bold text-slate-900 tabular-nums">{count}</p>
                <p className="text-xs text-slate-500">{label}</p>
              </div>
            </Card>
          ))}
        </section>

        {/* Pending queue — highest priority */}
        <section>
          <h2 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-amber-500 animate-pulse-dot" aria-hidden="true" />
            Pending Review
            {pending.length > 0 && (
              <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
                {pending.length}
              </span>
            )}
          </h2>

          {loading ? (
            <Card><p className="text-sm text-slate-400 text-center py-8">Loading…</p></Card>
          ) : pending.length === 0 ? (
            <Card>
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <div className="h-10 w-10 rounded-full bg-emerald-50 flex items-center justify-center">
                  <ShieldCheck className="h-5 w-5 text-emerald-600" aria-hidden="true" />
                </div>
                <p className="text-sm font-medium text-slate-700">All caught up</p>
                <p className="text-xs text-slate-400">No claims are waiting for a decision.</p>
              </div>
            </Card>
          ) : (
            <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-amber-50">
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Reference</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Producer</th>
                    <th className="hidden md:table-cell px-5 py-3 text-left text-xs font-semibold text-slate-500">Weight</th>
                    <th className="px-5 py-3 text-center text-xs font-semibold text-slate-500">Risk Score</th>
                    <th className="px-5 py-3 text-right text-xs font-semibold text-slate-500">Submitted</th>
                    <th className="px-5 py-3 w-10" />
                  </tr>
                </thead>
                <tbody>
                  {pending.map(claim => {
                    const vr = claim.verification_result;
                    return (
                      <tr key={claim.id} className="border-b border-slate-100 last:border-0 hover:bg-amber-50/50 transition-colors">
                        <td className="px-5 py-3.5">
                          <span className="font-mono text-xs font-semibold text-slate-700">{claim.reference_number}</span>
                        </td>
                        <td className="px-5 py-3.5">
                          <p className="font-medium text-slate-800">{claim.producer.name}</p>
                          <p className="text-xs text-slate-400">{claim.waste_category.split('—')[0].trim()}</p>
                        </td>
                        <td className="hidden md:table-cell px-5 py-3.5 font-mono text-xs text-slate-600 tabular-nums">
                          {formatWeight(claim.mass_balance.declared_input_kg)}
                        </td>
                        <td className="px-5 py-3.5">
                          {vr ? (
                            <div className="flex justify-center">
                              <RiskScore score={vr.risk_score} level={vr.risk_level} size="sm" />
                            </div>
                          ) : (
                            <span className="block text-center text-xs text-slate-400">—</span>
                          )}
                        </td>
                        <td className="px-5 py-3.5 text-right text-xs text-slate-500 whitespace-nowrap">
                          {formatDate(claim.submitted_at)}
                        </td>
                        <td className="px-5 py-3.5">
                          <Link
                            to={`/gov/claims/${claim.id}`}
                            className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700 transition-colors"
                            aria-label={`Review ${claim.reference_number}`}
                          >
                            Review <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Recently decided */}
        {(verified.length > 0 || rejected.length > 0) && (
          <section>
            <h2 className="text-sm font-semibold text-slate-800 mb-3">Recently Decided</h2>
            <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50">
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Reference</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Producer</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Decision</th>
                    <th className="px-5 py-3 text-right text-xs font-semibold text-slate-500">Updated</th>
                    <th className="px-5 py-3 w-10" />
                  </tr>
                </thead>
                <tbody>
                  {[...verified, ...rejected].map(claim => {
                    const sc = claimStatusConfig(claim.status);
                    return (
                      <tr key={claim.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 transition-colors">
                        <td className="px-5 py-3">
                          <span className="font-mono text-xs text-slate-700">{claim.reference_number}</span>
                        </td>
                        <td className="px-5 py-3 text-slate-700">{claim.producer.name}</td>
                        <td className="px-5 py-3">
                          <Badge className={`${sc.bg} ${sc.text}`}>{sc.label}</Badge>
                        </td>
                        <td className="px-5 py-3 text-right text-xs text-slate-500 whitespace-nowrap">
                          {formatDate(claim.updated_at)}
                        </td>
                        <td className="px-5 py-3">
                          <Link
                            to={`/gov/claims/${claim.id}`}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                            aria-label={`View ${claim.reference_number}`}
                          >
                            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
      <Footer />
    </div>
  );
}
