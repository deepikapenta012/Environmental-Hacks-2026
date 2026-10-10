import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldCheck, ShieldAlert, Clock, ArrowUpRight } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { RiskScore } from '@/components/ui/RiskScore';
import { fetchClaims } from '@/lib/api';
import type { RecyclingClaim } from '@/types';

export function VerificationStatusPage() {
  const [claims, setClaims] = useState<RecyclingClaim[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchClaims().then(r => setClaims(r.data)).finally(() => setLoading(false));
  }, []);

  const verified = claims.filter(c => c.status === 'VERIFIED');
  const flagged  = claims.filter(c => c.status === 'FLAGGED');
  const pending  = claims.filter(c => c.status === 'PENDING');

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Verification Status" subtitle="Real-time status of your claims" />
      <div className="flex-1 p-6 space-y-5 animate-fade-in">

        {/* Summary */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Verified', count: verified.length, icon: ShieldCheck, color: 'text-emerald-600', bg: 'bg-emerald-50' },
            { label: 'Flagged',  count: flagged.length,  icon: ShieldAlert,  color: 'text-orange-600',  bg: 'bg-orange-50'  },
            { label: 'Pending',  count: pending.length,  icon: Clock,        color: 'text-slate-500',   bg: 'bg-slate-100'  },
          ].map(({ label, count, icon: Icon, color, bg }) => (
            <Card key={label} className="flex items-center gap-4">
              <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${bg}`}>
                <Icon className={`h-5 w-5 ${color}`} aria-hidden="true" />
              </div>
              <div>
                <p className="text-xl font-bold text-slate-900">{count}</p>
                <p className="text-xs text-slate-500">{label}</p>
              </div>
            </Card>
          ))}
        </div>

        {/* Claim list */}
        {!loading && claims.length === 0 ? (
          <div className="text-center py-16 text-sm text-slate-500">
            No claims submitted yet. <Link to="/user/submit" className="text-teal-600 font-medium hover:underline">Submit your first claim.</Link>
          </div>
        ) : (
          <div className="space-y-3">
            {claims.map(claim => {
              const vr = claim.verification_result;
              return (
                <Card key={claim.id} padding="none">
                  <div className="flex items-center gap-4 p-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-slate-700">{claim.reference_number}</span>
                        <span className="text-slate-300">·</span>
                        <span className="text-xs text-slate-500 truncate">{claim.waste_category}</span>
                      </div>
                      <p className="text-xs text-slate-400 mt-0.5">
                        {claim.recycler.name} · {claim.mass_balance.declared_input_kg} kg declared
                      </p>
                      {vr && vr.flags.length > 0 && (
                        <p className="text-xs text-red-600 mt-1">
                          {vr.flags.length} flag{vr.flags.length > 1 ? 's' : ''}: {vr.flags[0].description.slice(0, 80)}…
                        </p>
                      )}
                    </div>
                    {vr && <RiskScore score={vr.risk_score} level={vr.risk_level} size="sm" />}
                    <Link
                      to={`/user/claims/${claim.id}`}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
                      aria-label={`View ${claim.reference_number}`}
                    >
                      <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
                    </Link>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}
