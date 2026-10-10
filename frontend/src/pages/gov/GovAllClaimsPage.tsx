import { useEffect, useState } from 'react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { GovClaimsTable } from '@/components/claims/GovClaimsTable';
import { fetchClaims } from '@/lib/api';
import type { ClaimStatus, RecyclingClaim } from '@/types';

const STATUS_FILTERS: { label: string; value: ClaimStatus | 'ALL' }[] = [
  { label: 'All',        value: 'ALL'        },
  { label: 'Awaiting Recycler', value: 'AWAITING_RECYCLER_CONFIRMATION' },
  { label: 'Received', value: 'RECEIVED' },
  { label: 'Processing', value: 'PROCESSING' },
  { label: 'Ready for Verification', value: 'READY_FOR_VERIFICATION' },
  { label: 'Clarification', value: 'AWAITING_CLARIFICATION' },
  { label: 'Awaiting Review', value: 'PENDING' },
  { label: 'Approved',   value: 'APPROVED'   },
  { label: 'Verified', value: 'VERIFIED' },
  { label: 'Flagged',    value: 'FLAGGED'    },
  { label: 'Rejected',   value: 'REJECTED'   },
];

export function GovAllClaimsPage() {
  const [claims, setClaims]   = useState<RecyclingClaim[]>([]);
  const [filter, setFilter]   = useState<ClaimStatus | 'ALL'>('ALL');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchClaims().then(r => setClaims(r.data)).finally(() => setLoading(false));
  }, []);

  const visible = filter === 'ALL' ? claims : claims.filter(c => c.status === filter);

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title="All Claims" subtitle="Every claim submitted to the platform" />
      <div className="flex-1 p-6 space-y-4 animate-fade-in">
        <nav className="flex gap-1 rounded-lg border border-slate-200 bg-white p-1 w-fit" aria-label="Filter by status">
          {STATUS_FILTERS.map(f => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              aria-pressed={filter === f.value}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                filter === f.value ? 'bg-indigo-600 text-white' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              {f.label}
            </button>
          ))}
        </nav>

        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
          {loading ? (
            <p className="text-sm text-slate-400 py-10 text-center">Loading…</p>
          ) : visible.length === 0 ? (
            <p className="text-sm text-slate-400 py-10 text-center">No claims match this filter.</p>
          ) : (
            <GovClaimsTable claims={visible} basePath="/gov/claims" />
          )}
        </div>
      </div>
      <Footer />
    </div>
  );
}
