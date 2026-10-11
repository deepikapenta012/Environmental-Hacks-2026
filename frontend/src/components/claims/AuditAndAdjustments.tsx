import { useState, type FormEvent } from 'react';
import { AlertTriangle, CheckCircle2, ShieldCheck } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { createMassBalanceAdjustment, fetchClaim, reviewMassBalanceAdjustment } from '@/lib/api';
import { formatDate, formatWeight, humanAuditChanges } from '@/lib/utils';
import type { AuditEventRecord, RecyclingClaim } from '@/types';

export function AuditTimeline({ events = [], chainValid }: { events?: AuditEventRecord[]; chainValid?: boolean }) {
  return <Card>
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-xs font-bold uppercase tracking-wide text-slate-600">Tamper-evident audit history</h2>
      <span className={`inline-flex items-center gap-1 text-[11px] font-semibold ${chainValid ? 'text-emerald-700' : 'text-red-700'}`}>
        {chainValid ? <ShieldCheck className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
        {chainValid ? 'Chain verified' : 'Integrity check failed'}
      </span>
    </div>
    {!events.length ? <p className="text-xs text-slate-500">No recorded events.</p> : <ol className="space-y-3">
      {events.map(event => <li key={event.id} className="border-t border-slate-100 pt-3 text-xs text-slate-600">
        <p className="font-semibold text-slate-800">#{event.sequence_no} {event.action_type.replace(/_/g, ' ')}
          <span className="font-normal"> · {event.actor_role ?? 'Legacy role unavailable'} · {event.actor_display_name ?? 'Actor unavailable'} · {event.occurred_at ? formatDate(event.occurred_at) : 'Legacy timestamp unavailable'}</span>
        </p>
        {!!humanAuditChanges(event.previous_values).length && <div className="mt-1"><strong>Before:</strong><ul className="ml-4 list-disc">{humanAuditChanges(event.previous_values).map((change, index) => <li key={index}>{change}</li>)}</ul></div>}
        {!!humanAuditChanges(event.new_values).length && <div className="mt-1"><strong>Recorded details:</strong><ul className="ml-4 list-disc">{humanAuditChanges(event.new_values).map((change, index) => <li key={index}>{change}</li>)}</ul></div>}
        {event.reason && <p className="mt-1"><strong>Reason:</strong> {event.reason}</p>}
        {event.legacy_event && <div className="mt-1 text-amber-700"><strong>Imported record:</strong> {humanAuditChanges(event.legacy_payload).join('; ') || 'Older audit details were retained for the record.'}</div>}
      </li>)}
    </ol>}
  </Card>;
}

export function MassBalanceAdjustments({ claim, allowCreate, allowReview, onUpdated }: {
  claim: RecyclingClaim;
  allowCreate?: boolean;
  allowReview?: boolean;
  onUpdated: (claim: RecyclingClaim) => void;
}) {
  const batches = claim.processing_batches ?? [];
  const batchesWithIds = batches.filter(batch => typeof batch.batch_id === 'string' && batch.batch_id.trim().length > 0);
  const [batchId, setBatchId] = useState(batchesWithIds[0]?.batch_id ?? '');
  const [field, setField] = useState<'PROCESSED_OUTPUT' | 'RESIDUAL_WASTE' | 'RECOVERED_MATERIAL'>('PROCESSED_OUTPUT');
  const [quantity, setQuantity] = useState('');
  const [category, setCategory] = useState('MEASUREMENT_CORRECTION');
  const [reason, setReason] = useState('');
  const [evidenceIds, setEvidenceIds] = useState<string[]>([]);
  const [decision, setDecision] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const isFinalized = ['APPROVED', 'REJECTED', 'VERIFIED'].includes(claim.status);
  const canSubmitAdjustment = allowCreate && !isFinalized && batchesWithIds.length > 0;

  const refresh = async () => onUpdated(await fetchClaim(claim.id));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (!batchId.trim() || !batchesWithIds.some(batch => batch.batch_id === batchId)) {
      setError('Choose a processing batch before submitting the adjustment.');
      return;
    }
    setBusy(true); setError(''); setMessage('');
    try {
      await createMassBalanceAdjustment(claim.id, {
        processing_batch_id: batchId, field,
        material_index: field === 'RECOVERED_MATERIAL' ? 0 : undefined,
        corrected_quantity: Number(quantity), category, reason, supporting_evidence_ids: evidenceIds,
      });
      setQuantity(''); setReason(''); setMessage('Adjustment submitted for government review.');
      try { await refresh(); }
      catch { setError('The adjustment was submitted, but the claim could not be refreshed. Reload the claim to see its status.'); }
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Adjustment request failed.'); }
    finally { setBusy(false); }
  };
  const review = async (id: string, approve: boolean) => {
    setBusy(true); setError(''); setMessage('');
    try {
      const updated = await reviewMassBalanceAdjustment(claim.id, id, approve, decision);
      onUpdated(updated); setDecision(''); setMessage(approve ? 'Adjustment approved and reconciliation recalculated.' : 'Adjustment rejected. Original measurements remain in place.');
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Adjustment review failed.'); }
    finally { setBusy(false); }
  };

  return <Card>
    <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-600">Mass-balance adjustments</h2>
    {claim.original_mass_balance && <p className="mb-3 text-xs text-slate-600">
      Original processing total: {claim.original_mass_balance.processed_output_kg === null ? '—' : formatWeight(claim.original_mass_balance.processed_output_kg)} ·
      Current approved total: {claim.mass_balance.processed_output_kg === null ? '—' : formatWeight(claim.mass_balance.processed_output_kg)}
    </p>}
    {(claim.mass_balance_adjustments ?? []).map(adjustment => <div key={adjustment.id} className="mb-3 rounded-lg border border-slate-200 p-3 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong>{adjustment.processing_batch_id} · {adjustment.field.replace(/_/g, ' ')}</strong>
        <span className="font-semibold">{adjustment.review_status}</span>
      </div>
      <p className="mt-1">{formatWeight(adjustment.original_quantity)} → {formatWeight(adjustment.corrected_quantity)} · {adjustment.category.replace(/_/g, ' ')}</p>
      <p className="mt-1">Reason: {adjustment.reason}</p>
      <p className="mt-1 text-slate-500">Requested by {adjustment.created_by_name ?? adjustment.created_by_user_id} · {formatDate(adjustment.created_at)}</p>
      {adjustment.supporting_evidence_ids.length > 0 && <p className="mt-1">Evidence: {adjustment.supporting_evidence_ids.join(', ')}</p>}
      {adjustment.review_decision && <p className="mt-1">Review: {adjustment.review_decision} · {adjustment.reviewed_by_name} · {adjustment.reviewed_at ? formatDate(adjustment.reviewed_at) : ''}</p>}
      {allowReview && adjustment.review_status === 'PENDING' && <div className="mt-2 space-y-2">
        <textarea aria-label="Adjustment review decision" required minLength={3} value={decision} onChange={e => setDecision(e.target.value)} placeholder="Review decision and rationale" className="w-full rounded-lg border border-slate-200 px-3 py-2" />
        <div className="flex gap-2"><Button size="sm" loading={busy} onClick={() => void review(adjustment.id, true)} disabled={decision.trim().length < 3}><CheckCircle2 className="h-4 w-4" /> Approve &amp; recalculate</Button>
          <Button variant="danger" size="sm" loading={busy} onClick={() => void review(adjustment.id, false)} disabled={decision.trim().length < 3}>Reject</Button></div>
      </div>}
    </div>)}
    {allowCreate && isFinalized && <p className="border-t border-slate-100 pt-3 text-xs text-slate-500">This claim is finalized and no longer accepts adjustment requests.</p>}
    {allowCreate && !isFinalized && batchesWithIds.length === 0 && <p className="border-t border-slate-100 pt-3 text-xs text-slate-500">A completed processing batch with a batch ID is needed before you can request an adjustment.</p>}
    {canSubmitAdjustment && <form onSubmit={submit} className="space-y-3 border-t border-slate-100 pt-3">
      <h3 className="text-xs font-semibold text-slate-700">Request a correction (requires officer review)</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-xs">Processing batch<select required value={batchId} onChange={e => setBatchId(e.target.value)} className="mt-1 w-full rounded border border-slate-200 p-2"><option value="">Choose a batch</option>{batchesWithIds.map(batch => <option key={batch.batch_id} value={batch.batch_id}>{batch.batch_id}</option>)}</select></label>
        <label className="text-xs">Measurement<select value={field} onChange={e => setField(e.target.value as typeof field)} className="mt-1 w-full rounded border border-slate-200 p-2"><option value="PROCESSED_OUTPUT">Processed output</option><option value="RECOVERED_MATERIAL">Recovered material (first entry)</option><option value="RESIDUAL_WASTE">Residual waste</option></select></label>
        <label className="text-xs">Corrected quantity (kg)<input required type="number" min="0" step="0.001" value={quantity} onChange={e => setQuantity(e.target.value)} className="mt-1 w-full rounded border border-slate-200 p-2" /></label>
        <label className="text-xs">Category<select value={category} onChange={e => setCategory(e.target.value)} className="mt-1 w-full rounded border border-slate-200 p-2"><option value="MEASUREMENT_CORRECTION">Measurement correction</option><option value="DOCUMENTED_PROCESSING_LOSS">Documented processing loss</option><option value="DATA_ENTRY_CORRECTION">Data-entry correction</option></select></label>
      </div>
      <label className="block text-xs">Reason<textarea required minLength={5} value={reason} onChange={e => setReason(e.target.value)} className="mt-1 w-full rounded border border-slate-200 p-2" /></label>
      {!!claim.evidence.length && <fieldset className="space-y-1"><legend className="text-xs">Supporting evidence</legend>{claim.evidence.map(evidence => <label key={evidence.id} className="flex items-center gap-2 text-xs"><input type="checkbox" checked={evidenceIds.includes(evidence.id)} onChange={e => setEvidenceIds(ids => e.target.checked ? [...ids, evidence.id] : ids.filter(id => id !== evidence.id))} />{evidence.filename}</label>)}</fieldset>}
      <p className="text-[11px] text-slate-500">Choose a batch, enter a corrected quantity, and provide a reason of at least five characters.</p>
      <Button type="submit" size="sm" loading={busy}>Submit adjustment</Button>
    </form>}
    {error && <p role="alert" className="mt-2 text-xs text-red-700">{error}</p>}
    {message && <p role="status" className="mt-2 text-xs text-emerald-700">{message}</p>}
  </Card>;
}
