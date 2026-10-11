import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, FilePlus } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Badge } from '@/components/ui/Badge';
import { RiskScore } from '@/components/ui/RiskScore';
import { Button } from '@/components/ui/Button';
import { fetchClaims } from '@/lib/api';
import { claimStatusConfig, formatDate, formatWeight } from '@/lib/utils';
import type { RecyclingClaim } from '@/types';

export function MyClaimsPage() {
  const [claims, setClaims] = useState<RecyclingClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchClaims().then(r => setClaims(r.data)).catch(() => setError('Could not load your claims. Please try again.')).finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="My Claims" subtitle="All claims you have submitted" />
      <div className="flex-1 p-6 animate-fade-in">
        {loading ? <p className="py-16 text-center text-sm text-slate-500">Loading your claims…</p> : error ? (
          <div role="alert" className="py-16 text-center"><p className="text-sm text-red-700">{error}</p><button className="mt-3 text-sm font-medium text-indigo-600" onClick={() => window.location.reload()}>Retry</button></div>
        ) : claims.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
            <div className="h-14 w-14 rounded-full bg-slate-100 flex items-center justify-center">
              <FilePlus className="h-6 w-6 text-slate-400" aria-hidden="true" />
            </div>
            <p className="text-sm font-medium text-slate-600">No claims yet</p>
            <p className="text-xs text-slate-400">Submit your first recycling claim to get started.</p>
            <Link to="/user/submit"><Button>Submit a Claim</Button></Link>
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Reference</th>
                  <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Category</th>
                  <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Weight</th>
                  <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">Status</th>
                  <th className="px-5 py-3 text-center text-xs font-semibold text-slate-500">Risk</th>
                  <th className="px-5 py-3 text-right text-xs font-semibold text-slate-500">Submitted</th>
                  <th className="px-5 py-3 w-10" />
                </tr>
              </thead>
              <tbody>
                {claims.map(claim => {
                  const sc = claimStatusConfig(claim.status);
                  const vr = claim.verification_result;
                  return (
                    <tr key={claim.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50 transition-colors">
                      <td className="px-5 py-3.5">
                        <span className="font-mono text-xs text-slate-700">{claim.reference_number}</span>
                      </td>
                      <td className="px-5 py-3.5 text-xs text-slate-600 max-w-[180px] truncate">{claim.waste_category}</td>
                      <td className="px-5 py-3.5 font-mono text-xs text-slate-700 tabular-nums">
                        {formatWeight(claim.mass_balance.declared_input_kg)}
                      </td>
                      <td className="px-5 py-3.5">
                        <Badge className={`${sc.bg} ${sc.text}`}>{sc.label}</Badge>
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
                          to={`/user/claims/${claim.id}`}
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
        )}
      </div>
      <Footer />
    </div>
  );
}
