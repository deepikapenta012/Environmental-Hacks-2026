import { useEffect, useMemo, useState } from 'react';
import { ClipboardList, ShieldAlert, CheckCircle2, Clock, Search, AlertTriangle, XCircle, MessageSquareWarning } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card, CardHeader, CardTitle } from '@/components/ui/Card';
import { StatCard } from '@/components/dashboard/StatCard';
import { fetchClaims } from '@/lib/api';
import { GovClaimsTable } from '@/components/claims/GovClaimsTable';
import type { RecyclingClaim } from '@/types';
import { useAuth } from '@/lib/auth';

const PAGE_SIZE = 25;

export function GovDashboardPage() {
  const { user } = useAuth();
  const [claims, setClaims] = useState<RecyclingClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('ALL');
  const [risk, setRisk] = useState('ALL');
  const [facility, setFacility] = useState('ALL');
  const [flagCategory, setFlagCategory] = useState('ALL');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [sort, setSort] = useState('newest');
  const [page, setPage] = useState(1);

  useEffect(() => {
    let active = true;
    fetchClaims()
      .then(r => { if (active) setClaims(r.data); })
      .catch(error => { if (active) setLoadError(error instanceof Error ? error.message : 'Could not load assigned claims.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const total = claims.length;
  const awaiting = claims.filter(c => ['SUBMITTED', 'AWAITING_RECYCLER_CONFIRMATION', 'READY_FOR_VERIFICATION', 'PENDING', 'FLAGGED'].includes(c.status)).length;
  const highCritical = claims.filter(c => ['HIGH', 'CRITICAL'].includes(c.verification_result?.risk_level || '')).length;
  const unresolved = claims.filter(c => c.verification_result?.flags.some(f => (f.status || 'ACTIVE') === 'ACTIVE')).length;
  const clarification = claims.filter(c => c.status === 'AWAITING_CLARIFICATION').length;
  const approved = claims.filter(c => c.status === 'APPROVED' || c.status === 'VERIFIED').length;
  const rejected = claims.filter(c => c.status === 'REJECTED').length;
  const avgRisk = total ? (claims.reduce((sum, c) => sum + (c.verification_result?.risk_score ?? 0), 0) / total).toFixed(1) : '—';
  const facilities = [...new Set(claims.map(c => c.recycler.name).filter(Boolean))].sort();

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const result = claims.filter(c => {
      const matchesSearch = !needle || [c.reference_number, c.producer.name, c.recycler.name].some(value => value.toLowerCase().includes(needle));
      const matchesStatus = status === 'ALL' || c.status === status;
      const matchesRisk = risk === 'ALL' || c.verification_result?.risk_level === risk;
      const matchesFacility = facility === 'ALL' || c.recycler.name === facility;
      const submitted = c.submitted_at.slice(0, 10);
      const matchesDates = (!dateFrom || submitted >= dateFrom) && (!dateTo || submitted <= dateTo);
      const matchesFlag = flagCategory === 'ALL' || c.verification_result?.flags.some(f =>
        (f.status || 'ACTIVE') === 'ACTIVE' && (f.rule_category === flagCategory || f.layer === flagCategory));
      return matchesSearch && matchesStatus && matchesRisk && matchesFacility && matchesDates && matchesFlag;
    });
    return result.sort((a, b) => {
      if (sort === 'oldest') return a.submitted_at.localeCompare(b.submitted_at) || a.id.localeCompare(b.id);
      if (sort === 'risk') return (b.verification_result?.risk_score ?? -1) - (a.verification_result?.risk_score ?? -1) || a.id.localeCompare(b.id);
      return b.submitted_at.localeCompare(a.submitted_at) || a.id.localeCompare(b.id);
    });
  }, [claims, search, status, risk, facility, dateFrom, dateTo, flagCategory, sort]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageClaims = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const change = (setter: (value: string) => void) => (value: string) => { setter(value); setPage(1); };

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Government Dashboard" subtitle={`Monitor recycling claims and evidence, ${user?.name} · ${user?.organisation}`} />
      <div className="flex-1 p-6 space-y-6 animate-fade-in">
        <section className="grid grid-cols-2 gap-4 sm:grid-cols-4" aria-label="Jurisdiction claim totals">
          <StatCard label="Total Claims" value={total} icon={ClipboardList} accent="teal" />
          <StatCard label="Awaiting Review" value={awaiting} icon={Clock} accent="amber" />
          <StatCard label="High / Critical" value={highCritical} icon={ShieldAlert} accent="red" />
          <StatCard label="Claims With Active Flags" value={unresolved} icon={AlertTriangle} accent="amber" />
          <StatCard label="Clarification" value={clarification} icon={MessageSquareWarning} accent="default" />
          <StatCard label="Approved" value={approved} icon={CheckCircle2} accent="emerald" />
          <StatCard label="Rejected" value={rejected} icon={XCircle} accent="red" />
          <StatCard label="Average Risk" value={avgRisk} icon={ClipboardList} accent="default" subtext="out of 100" />
        </section>

        <Card>
          <CardHeader><CardTitle>Jurisdiction Claims</CardTitle><span className="text-xs text-slate-500">{filtered.length} matching · {total} total</span></CardHeader>
          <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label className="relative"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" /><input aria-label="Search claims" value={search} onChange={e => change(setSearch)(e.target.value)} placeholder="Search reference, producer, facility" className="w-full rounded-md border py-2 pl-8 pr-2 text-sm" /></label>
            <select aria-label="Filter by status" value={status} onChange={e => change(setStatus)(e.target.value)} className="rounded-md border px-2 py-2 text-sm"><option value="ALL">All statuses</option>{['SUBMITTED','AWAITING_RECYCLER_CONFIRMATION','RECEIVED','PROCESSING','READY_FOR_VERIFICATION','PENDING','FLAGGED','AWAITING_CLARIFICATION','APPROVED','VERIFIED','REJECTED'].map(value => <option key={value} value={value}>{value.replace(/_/g, ' ')}</option>)}</select>
            <select aria-label="Filter by risk" value={risk} onChange={e => change(setRisk)(e.target.value)} className="rounded-md border px-2 py-2 text-sm"><option value="ALL">All risk bands</option>{['LOW','MEDIUM','HIGH','CRITICAL'].map(value => <option key={value}>{value}</option>)}</select>
            <select aria-label="Filter by facility" value={facility} onChange={e => change(setFacility)(e.target.value)} className="rounded-md border px-2 py-2 text-sm"><option value="ALL">All recycler facilities</option>{facilities.map(value => <option key={value}>{value}</option>)}</select>
            <select aria-label="Filter by flag category" value={flagCategory} onChange={e => change(setFlagCategory)(e.target.value)} className="rounded-md border px-2 py-2 text-sm"><option value="ALL">All flag categories</option>{['mass_balance','transport','evidence','data_quality','historical','DOCUMENT','GEOSPATIAL','DUPLICATE'].map(value => <option key={value}>{value}</option>)}</select>
            <label className="flex items-center gap-2 rounded-md border px-2 text-xs text-slate-500">From<input aria-label="From date" type="date" value={dateFrom} onChange={e => change(setDateFrom)(e.target.value)} className="min-w-0 flex-1 py-2 text-sm text-slate-700" /></label>
            <label className="flex items-center gap-2 rounded-md border px-2 text-xs text-slate-500">To<input aria-label="To date" type="date" value={dateTo} onChange={e => change(setDateTo)(e.target.value)} className="min-w-0 flex-1 py-2 text-sm text-slate-700" /></label>
            <select aria-label="Sort claims" value={sort} onChange={e => change(setSort)(e.target.value)} className="rounded-md border px-2 py-2 text-sm"><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="risk">Highest risk first</option></select>
          </div>
          {loading ? <p className="py-8 text-center text-sm text-slate-400">Loading claims…</p>
            : loadError ? <p className="py-8 text-center text-sm text-red-700" role="alert">{loadError}</p>
              : filtered.length === 0 ? <p className="py-8 text-center text-sm text-slate-400">No claims match these filters.</p>
                : <><GovClaimsTable claims={pageClaims} basePath="/gov/claims" /><div className="mt-4 flex items-center justify-between text-sm"><span className="text-slate-500">Page {page} of {pageCount}</span><div className="flex gap-2"><button disabled={page <= 1} onClick={() => setPage(value => Math.max(1, value - 1))} className="rounded border px-3 py-1.5 disabled:opacity-40">Previous</button><button disabled={page >= pageCount} onClick={() => setPage(value => Math.min(pageCount, value + 1))} className="rounded border px-3 py-1.5 disabled:opacity-40">Next</button></div></div></>}
        </Card>
      </div>
      <Footer />
    </div>
  );
}
