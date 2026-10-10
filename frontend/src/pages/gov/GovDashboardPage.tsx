import { useEffect, useState } from 'react';
import { ClipboardList, ShieldAlert, CheckCircle2, Clock, TrendingUp } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card, CardHeader, CardTitle } from '@/components/ui/Card';
import { StatCard } from '@/components/dashboard/StatCard';
import { fetchClaims } from '@/lib/api';
import { GovClaimsTable } from '@/components/claims/GovClaimsTable';
import type { RecyclingClaim } from '@/types';
import { useAuth } from '@/lib/auth';

export function GovDashboardPage() {
  const { user } = useAuth();
  const [claims, setClaims] = useState<RecyclingClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    fetchClaims()
      .then(r => setClaims(r.data))
      .catch(error => setLoadError(error instanceof Error ? error.message : 'Could not load assigned claims.'))
      .finally(() => setLoading(false));
  }, []);

  const verified  = claims.filter(c => c.status === 'VERIFIED' || c.status === 'APPROVED').length;
  const flagged   = claims.filter(c => c.status === 'FLAGGED').length;
  const pending   = claims.filter(c => c.status === 'PENDING' || c.status === 'FLAGGED').length;
  const avgRisk   = claims.length
    ? (claims.reduce((s, c) => s + (c.verification_result?.risk_score ?? 0), 0) / claims.length).toFixed(1)
    : '—';

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Government Dashboard" subtitle={`Monitor recycling claims and evidence, ${user?.name} · ${user?.organisation}`} />
      <div className="flex-1 p-6 space-y-6 animate-fade-in">

        <section className="grid grid-cols-2 gap-4 sm:grid-cols-4" aria-label="KPIs">
          <StatCard label="Total Claims"  value={claims.length} icon={ClipboardList} accent="teal" />
          <StatCard label="Verified"      value={verified}      icon={CheckCircle2}  accent="emerald" />
          <StatCard label="Flagged"       value={flagged}       icon={ShieldAlert}   accent="amber" />
          <StatCard label="Avg Risk"      value={avgRisk}       icon={TrendingUp}    accent="default" subtext="out of 100" />
        </section>

        <Card>
          <CardHeader>
            <CardTitle>All Submitted Claims</CardTitle>
            {pending > 0 && (
              <span className="flex items-center gap-1.5 text-xs text-amber-600 font-medium">
                <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                {pending} pending review
              </span>
            )}
          </CardHeader>
          {loading ? (
            <p className="text-sm text-slate-400 py-8 text-center">Loading claims…</p>
          ) : loadError ? (
            <p className="text-sm text-red-700 py-8 text-center" role="alert">{loadError}</p>
          ) : claims.length === 0 ? (
            <p className="text-sm text-slate-400 py-8 text-center">No claims are currently assigned to your jurisdiction.</p>
          ) : (
            <GovClaimsTable claims={claims} basePath="/gov/claims" />
          )}
        </Card>
      </div>
      <Footer />
    </div>
  );
}
