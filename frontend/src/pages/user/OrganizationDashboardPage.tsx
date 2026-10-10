import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CircleCheck, Clock3, FilePlus2, Files } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { StatCard } from '@/components/dashboard/StatCard';
import { fetchClaims } from '@/lib/api';
import { claimStatusConfig, formatDate } from '@/lib/utils';
import { useAuth } from '@/lib/auth';
import type { RecyclingClaim } from '@/types';

export function OrganizationDashboardPage() {
  const { user } = useAuth();
  const [claims, setClaims] = useState<RecyclingClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchClaims()
      .then(response => setClaims(response.data))
      .catch(loadError => setError(loadError instanceof Error ? loadError.message : 'Could not load organization claims.'))
      .finally(() => setLoading(false));
  }, []);

  const awaiting = claims.filter(claim => ['AWAITING_RECYCLER_CONFIRMATION', 'AWAITING_CLARIFICATION'].includes(claim.status)).length;
  const completed = claims.filter(claim => ['APPROVED', 'VERIFIED'].includes(claim.status)).length;
  const recent = [...claims].sort((a, b) => Date.parse(b.submitted_at) - Date.parse(a.submitted_at)).slice(0, 5);

  return (
    <div className="flex min-h-full flex-col">
      <TopBar title="Factory Coordinator Dashboard" subtitle={`Welcome, ${user?.name} · ${user?.organisation}`} />
      <main className="flex-1 space-y-6 p-6 animate-fade-in">
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3" aria-label="Organization claim summary">
          <StatCard label="Submitted claims" value={loading ? '—' : claims.length} icon={Files} accent="teal" />
          <StatCard label="Awaiting recycler" value={loading ? '—' : awaiting} icon={Clock3} accent="amber" />
          <StatCard label="Approved" value={loading ? '—' : completed} icon={CircleCheck} accent="emerald" />
        </section>

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-800">Your recycling claims</h2>
              <p className="mt-1 text-xs text-slate-500">Submit e-waste handovers and follow recycler and government review.</p>
            </div>
            <Link to="/user/submit"><Button><FilePlus2 className="h-4 w-4" aria-hidden="true" />Submit a claim</Button></Link>
          </div>
        </Card>

        {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
        <Card>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-800">Recent claims</h2>
            <Link className="inline-flex items-center gap-1 text-xs font-medium text-teal-700 hover:text-teal-800" to="/user/claims">View all <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
          </div>
          {loading ? <p className="py-8 text-center text-sm text-slate-400">Loading claims…</p>
            : recent.length === 0 ? <p className="py-8 text-center text-sm text-slate-500">No claims yet. Submit a claim to start a recycling handover.</p>
              : <div className="divide-y divide-slate-100">
                {recent.map(claim => {
                  const status = claimStatusConfig(claim.status);
                  return <Link key={claim.id} to={`/user/claims/${claim.id}`} className="flex flex-wrap items-center justify-between gap-3 py-3 hover:bg-slate-50">
                    <span><span className="block font-mono text-xs font-semibold text-slate-700">{claim.reference_number}</span><span className="mt-1 block text-xs text-slate-500">{claim.recycler.name} · {formatDate(claim.submitted_at)}</span></span>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${status.bg} ${status.text}`}>{status.label}</span>
                  </Link>;
                })}
              </div>}
        </Card>
      </main>
      <Footer />
    </div>
  );
}
