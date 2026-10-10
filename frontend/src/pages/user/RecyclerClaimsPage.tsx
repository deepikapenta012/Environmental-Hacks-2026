import { useEffect, useState, type FormEvent } from 'react';
import { AlertCircle, CheckCircle2, Clock3, PackageCheck, Recycle, Scale } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { StatCard } from '@/components/dashboard/StatCard';
import { EvidencePanel } from '@/components/claims/EvidencePanel';
import { AuditTimeline, MassBalanceAdjustments } from '@/components/claims/AuditAndAdjustments';
import { Footer } from '@/components/layout/Footer';
import { TopBar } from '@/components/layout/TopBar';
import { fetchAssignedClaims, confirmClaimReceipt, submitClaimProcessing } from '@/lib/api';
import { claimStatusConfig, formatDate, formatWeight } from '@/lib/utils';
import { useAuth } from '@/lib/auth';
import type { RecyclingClaim } from '@/types';

type BatchDraft = { processed: string; material: string; recovered: string; residual: string; date: string; notes: string };
const blankBatch = (): BatchDraft => ({ processed: '', material: 'Recovered materials', recovered: '', residual: '', date: new Date().toISOString().slice(0, 10), notes: '' });

function localDateTimeValue() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function AssignedClaimCard({ initialClaim }: { initialClaim: RecyclingClaim }) {
  const [claim, setClaim] = useState(initialClaim);
  const [receivedWeight, setReceivedWeight] = useState('');
  const [receivedAt, setReceivedAt] = useState(localDateTimeValue());
  const [batches, setBatches] = useState<BatchDraft[]>([blankBatch()]);
  const [recyclerNotes, setRecyclerNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const saveReceipt = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const updated = await confirmClaimReceipt(claim.id, {
        received_weight_kg: Number(receivedWeight),
        received_at: new Date(receivedAt).toISOString(),
        recycler_notes: recyclerNotes || undefined,
      });
      setClaim(updated);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Receipt confirmation failed.');
    } finally {
      setSaving(false);
    }
  };

  const saveProcessing = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const updated = await submitClaimProcessing(claim.id, {
        batches: batches.map(batch => ({
          processed_output_kg: Number(batch.processed),
          recovered_materials: [{ material: batch.material, quantity_kg: Number(batch.recovered) }],
          residual_waste_kg: Number(batch.residual),
          processing_date: batch.date,
          notes: batch.notes || undefined,
        })),
        corrects_previous: claim.status === 'AWAITING_CLARIFICATION',
        recycler_notes: recyclerNotes || undefined,
      });
      setClaim(updated);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Processing submission failed.');
    } finally {
      setSaving(false);
    }
  };

  const status = claimStatusConfig(claim.status);
  const balance = claim.mass_balance;

  return (
    <Card>
      <div className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-mono text-xs text-slate-400">{claim.reference_number}</p>
            <h2 className="text-base font-semibold text-slate-900">{claim.producer.name}</h2>
            <p className="text-xs text-slate-500">{claim.waste_category} · Collected {formatDate(claim.submitted_at)}</p>
          </div>
          <Badge className={`${status.bg} ${status.text}`}>{status.label}</Badge>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Producer declared</p>
            <p className="mt-1 text-lg font-bold text-slate-900">{formatWeight(balance.declared_input_kg)}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Destination</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{claim.recycler.name}</p>
            <p className="text-xs text-slate-500">{claim.recycler.registration_number}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Received</p>
            <p className="mt-1 text-lg font-bold text-slate-900">{balance.received_input_kg === null ? 'Not confirmed' : formatWeight(balance.received_input_kg)}</p>
            {claim.received_at && <p className="text-xs text-slate-500">{formatDate(claim.received_at)}</p>}
          </div>
        </div>

        {claim.clarification_reason && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">Officer requested clarification: {claim.clarification_reason}</p>}

        {(claim.status === 'AWAITING_RECYCLER_CONFIRMATION' || (claim.status === 'AWAITING_CLARIFICATION' && !claim.received_at)) && (
          <form onSubmit={saveReceipt} className="space-y-3 rounded-lg border border-amber-200 bg-amber-50/50 p-4">
            <h3 className="text-xs font-bold uppercase tracking-wide text-slate-600">Confirm Receipt</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs font-medium text-slate-600">
                Received Weight (kg)
                <input required type="number" min="0.1" step="0.1" value={receivedWeight} onChange={event => setReceivedWeight(event.target.value)} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              <label className="space-y-1 text-xs font-medium text-slate-600">
                Actual Arrival / Receipt Date &amp; Time
                <input required type="datetime-local" value={receivedAt} onChange={event => setReceivedAt(event.target.value)} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              <label className="space-y-1 text-xs font-medium text-slate-600 sm:col-span-2">
                Receipt discrepancy notes
                <textarea rows={2} value={recyclerNotes} onChange={event => setRecyclerNotes(event.target.value)} placeholder="Record any weight difference, packaging issue, or receiving exception." className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
            </div>
            <Button type="submit" size="sm" loading={saving}><CheckCircle2 className="h-4 w-4" /> Confirm Receipt</Button>
          </form>
        )}

        {['RECEIVED', 'PROCESSING', 'AWAITING_CLARIFICATION'].includes(claim.status) && claim.received_at && (
          <form onSubmit={saveProcessing} className="space-y-3 rounded-lg border border-blue-200 bg-blue-50/40 p-4">
            <h3 className="text-xs font-bold uppercase tracking-wide text-slate-600">Processing Batches</h3>
            {batches.map((batch, index) => <div key={index} className="grid grid-cols-1 gap-3 rounded-lg border border-blue-100 bg-white p-3 sm:grid-cols-2">
              <p className="text-xs font-semibold text-slate-600 sm:col-span-2">Batch {index + 1}</p>
              <label className="space-y-1 text-xs font-medium text-slate-600">Processed Output (kg)
                <input required type="number" min="0.1" step="0.1" value={batch.processed} onChange={event => setBatches(rows => rows.map((row, i) => i === index ? { ...row, processed: event.target.value } : row))} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              <label className="space-y-1 text-xs font-medium text-slate-600">Recovered Material
                <input required value={batch.material} onChange={event => setBatches(rows => rows.map((row, i) => i === index ? { ...row, material: event.target.value } : row))} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              <label className="space-y-1 text-xs font-medium text-slate-600">Recovered Quantity (kg)
                <input required type="number" min="0" step="0.1" value={batch.recovered} onChange={event => setBatches(rows => rows.map((row, i) => i === index ? { ...row, recovered: event.target.value } : row))} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              <label className="space-y-1 text-xs font-medium text-slate-600">Residual Waste (kg)
                <input required type="number" min="0" step="0.1" value={batch.residual} onChange={event => setBatches(rows => rows.map((row, i) => i === index ? { ...row, residual: event.target.value } : row))} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              <label className="space-y-1 text-xs font-medium text-slate-600">Processing Date
                <input required type="date" value={batch.date} onChange={event => setBatches(rows => rows.map((row, i) => i === index ? { ...row, date: event.target.value } : row))} className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              <label className="space-y-1 text-xs font-medium text-slate-600 sm:col-span-2">Batch Notes
                <textarea rows={2} value={batch.notes} onChange={event => setBatches(rows => rows.map((row, i) => i === index ? { ...row, notes: event.target.value } : row))} className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
              {batches.length > 1 && <button type="button" className="text-left text-xs text-red-600" onClick={() => setBatches(rows => rows.filter((_, i) => i !== index))}>Remove batch</button>}
            </div>)}
            <div className="flex gap-2">
              <Button type="button" variant="secondary" size="sm" onClick={() => setBatches(rows => [...rows, blankBatch()])}>Add batch</Button>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-xs font-medium text-slate-600 sm:col-span-2">Recycler Notes
                <textarea rows={2} value={recyclerNotes} onChange={event => setRecyclerNotes(event.target.value)} className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
              </label>
            </div>
            <Button type="submit" size="sm" loading={saving}><Scale className="h-4 w-4" /> Submit Processing &amp; Verify</Button>
          </form>
        )}

        {claim.processing_batches?.length ? <div className="space-y-2 rounded-lg border border-slate-200 p-4">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-600">Submitted Processing Batches</h3>
          {claim.processing_batches.map(batch => <p key={batch.batch_id} className="text-xs text-slate-600">{batch.batch_id}: {formatWeight(batch.processed_output_kg)} processed · {formatDate(batch.processing_date)} · submitted by {batch.submitted_by.name} at {formatDate(batch.submitted_at)}</p>)}
        </div> : null}
        <MassBalanceAdjustments claim={claim} allowCreate={!!claim.processing_completed_at} onUpdated={setClaim} />
        <AuditTimeline events={claim.audit_events} chainValid={claim.audit_chain_valid} />

        {claim.processing_completed_at && (
          <div className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 p-4 text-sm sm:grid-cols-3">
            <p><span className="block text-[10px] font-semibold uppercase text-slate-500">Processed Output</span>{balance.processed_output_kg === null ? '—' : formatWeight(balance.processed_output_kg)}</p>
            <p><span className="block text-[10px] font-semibold uppercase text-slate-500">Recovered</span>{formatWeight(balance.recovered_materials.reduce((sum, item) => sum + item.quantity_kg, 0))}</p>
            <p><span className="block text-[10px] font-semibold uppercase text-slate-500">Residual</span>{balance.residual_waste_kg === null ? '—' : formatWeight(balance.residual_waste_kg)}</p>
            {claim.processing_date && <p className="text-xs text-slate-500 sm:col-span-3">Processing date: {claim.processing_date}. {claim.recycler_notes}</p>}
          </div>
        )}

        {error && <p className="flex items-start gap-2 text-xs text-red-700" role="alert"><AlertCircle className="h-4 w-4 shrink-0" />{error}</p>}
        <EvidencePanel
          claimId={claim.id}
          evidence={claim.evidence}
          status={claim.status}
          receivedAt={claim.received_at}
          processingCompletedAt={claim.processing_completed_at}
          party="RECYCLER"
          onClaimUpdated={setClaim}
        />

        {claim.verification_result && (
          <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-800">
            ChainGuard verification complete: risk score <strong>{claim.verification_result.risk_score}</strong> ({claim.verification_result.risk_level}) · {claim.verification_result.flags.length} explainable flag(s).
          </div>
        )}
      </div>
    </Card>
  );
}

export function RecyclerClaimsPage() {
  const { user } = useAuth();
  const [claims, setClaims] = useState<RecyclingClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchAssignedClaims()
      .then(setClaims)
      .catch(loadError => setError(loadError instanceof Error ? loadError.message : 'Could not load assigned claims.'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex min-h-full flex-col">
      <TopBar title="Recycler Dashboard" subtitle={`${user?.organisation ?? 'Recycler facility'} · Incoming claims for your assigned company`} />
      <div className="flex-1 space-y-4 p-6 animate-fade-in">
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3" aria-label="Recycler work summary">
          <StatCard label="Assigned claims" value={loading ? '—' : claims.length} icon={PackageCheck} accent="teal" />
          <StatCard label="Awaiting receipt" value={loading ? '—' : claims.filter(claim => !claim.received_at).length} icon={Clock3} accent="amber" />
          <StatCard label="Received, processing or complete" value={loading ? '—' : claims.filter(claim => Boolean(claim.received_at)).length} icon={Recycle} accent="emerald" />
        </section>
        {loading && <p className="py-8 text-center text-sm text-slate-400">Loading assigned claims…</p>}
        {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
        {!loading && !error && claims.length === 0 && <p className="py-10 text-center text-sm text-slate-500">No claims are assigned to your recycler account yet.</p>}
        {claims.map(claim => <AssignedClaimCard key={claim.id} initialClaim={claim} />)}
      </div>
      <Footer />
    </div>
  );
}
