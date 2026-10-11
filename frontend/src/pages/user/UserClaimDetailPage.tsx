import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Scale, Truck, ShieldCheck, Layers } from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { RiskScore } from '@/components/ui/RiskScore';
import { VerificationFlags } from '@/components/verification/VerificationFlags';
import { MassBalancePanel } from '@/components/verification/MassBalancePanel';
import { ExplainabilityBreakdown } from '@/components/verification/ExplainabilityBreakdown';
import { EvidencePanel } from '@/components/claims/EvidencePanel';
import { AuditTimeline, MassBalanceAdjustments } from '@/components/claims/AuditAndAdjustments';
import { fetchClaim } from '@/lib/api';
import { claimStatusConfig, formatDate, formatWeight } from '@/lib/utils';
import { useAuth } from '@/lib/auth';
import type { RecyclingClaim } from '@/types';

type Tab = 'flags' | 'mass_balance' | 'transport' | 'explainability';

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'flags',         label: 'Flags',          icon: ShieldCheck },
  { id: 'mass_balance',  label: 'Mass Balance',   icon: Scale       },
  { id: 'transport',     label: 'Transport',      icon: Truck       },
  { id: 'explainability',label: 'Explainability', icon: Layers      },
];

export function UserClaimDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [claim, setClaim] = useState<RecyclingClaim | null>(null);
  const [tab, setTab] = useState<Tab>('flags');
  const { user } = useAuth();

  useEffect(() => {
    if (id) fetchClaim(id).then(setClaim);
  }, [id]);

  if (!claim) return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Claim Detail" />
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    </div>
  );

  const vr = claim.verification_result;
  const sc = claimStatusConfig(claim.status);
  const belongsToRecyclerFacility = user?.role === 'RECYCLER_EMPLOYEE'
    && !!claim.recycler_facility_id
    && user.facility_ids.includes(claim.recycler_facility_id);

  return (
    <div className="flex flex-col min-h-full">
      <TopBar title={claim.reference_number} subtitle={`Submitted ${formatDate(claim.submitted_at)}`} />
      <div className="flex-1 p-6 space-y-5 animate-fade-in">
        <div className="flex items-center gap-3">
          <Link to="/user/claims">
            <Button variant="ghost" size="sm"><ArrowLeft className="h-4 w-4" aria-hidden="true" /> My Claims</Button>
          </Link>
          <Badge className={`${sc.bg} ${sc.text}`}>{sc.label}</Badge>
        </div>

        <Card>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {[{ label: 'Producer', org: claim.producer }, { label: 'Recycler', org: claim.recycler }].map(({ label, org }) => (
              <div key={label}>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
                <p className="mt-1 text-sm font-semibold text-slate-800">{org.name}</p>
                <p className="text-xs text-slate-500">{org.registration_number} · {org.city}</p>
              </div>
            ))}
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Declared weight</p>
              <p className="mt-1 text-sm font-semibold text-slate-800">{formatWeight(claim.mass_balance.declared_input_kg)}</p>
              <p className="text-xs text-slate-500">{claim.waste_category}</p>
            </div>
          </div>
        </Card>

        <EvidencePanel
          claimId={claim.id}
          claim={claim}
          evidence={claim.evidence}
          status={claim.status}
          receivedAt={claim.received_at}
          processingCompletedAt={claim.processing_completed_at}
          party={belongsToRecyclerFacility ? 'RECYCLER' : 'PRODUCER'}
          onClaimUpdated={setClaim}
        />
        <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700">Mass balance adjustments</summary>
          <div className="mt-3"><MassBalanceAdjustments claim={claim} onUpdated={setClaim} /></div>
        </details>
        <details className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700">Audit history</summary>
          <div className="mt-3"><AuditTimeline events={claim.audit_events} chainValid={claim.audit_chain_valid} /></div>
        </details>

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-5">
            <div>
              <nav className="flex gap-0.5 rounded-lg border border-slate-200 bg-slate-50 p-1 mb-4" role="tablist">
                {TABS.map(({ id: tid, label, icon: Icon }) => (
                  <button
                    key={tid}
                    role="tab"
                    aria-selected={tab === tid}
                    onClick={() => setTab(tid)}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors ${
                      tab === tid ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden="true" /><span className="hidden sm:inline">{label}</span>
                  </button>
                ))}
              </nav>
              <Card>
                {tab === 'flags' && (vr ? <VerificationFlags flags={vr.flags} /> : <p className="text-sm text-slate-500 text-center py-8">No result yet.</p>)}
                {tab === 'mass_balance' && <MassBalancePanel balance={claim.mass_balance} />}
                {tab === 'transport' && (
                  <div className="space-y-3">
                    {claim.transport.map((leg, i) => (
                      <div key={i} className="rounded-lg border border-slate-200 p-4 space-y-2">
                        <p className="font-mono text-sm font-semibold text-slate-800">{leg.vehicle_registration} · {leg.driver_name}</p>
                        <div className="grid grid-cols-2 gap-2 text-xs text-slate-600">
                          <span>Departed: {formatDate(leg.departed_at)}</span>
                          <span>Expected arrival (producer): {formatDate(leg.arrived_at)}</span>
                          <span>Declared: {formatWeight(leg.declared_weight_kg)}</span>
                          <span>Received: {leg.actual_weight_kg ? formatWeight(leg.actual_weight_kg) : '—'}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {tab === 'explainability' && (vr ? <ExplainabilityBreakdown data={vr.explainability} /> : <p className="text-sm text-slate-500 text-center py-8">No data.</p>)}
              </Card>
            </div>
          </div>

          <aside>
            {vr ? (
              <Card>
                <div className="flex flex-col items-center gap-3 py-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Verification Result</p>
                  <RiskScore score={vr.risk_score} level={vr.risk_level} size="lg" />
                  <div className="w-full mt-2 space-y-1.5">
                    {[
                      { label: 'Flags',    value: vr.flags.length },
                      { label: 'Critical', value: vr.flags.filter(f => f.severity === 'CRITICAL').length },
                      { label: 'Verified', value: formatDate(vr.verified_at) },
                    ].map(({ label, value }) => (
                      <div key={label} className="flex justify-between text-xs">
                        <span className="text-slate-500">{label}</span>
                        <span className="font-medium text-slate-800">{value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            ) : (
              <Card><p className="text-sm text-slate-500 text-center py-6">No result yet.</p></Card>
            )}
          </aside>
        </div>
      </div>
      <Footer />
    </div>
  );
}
