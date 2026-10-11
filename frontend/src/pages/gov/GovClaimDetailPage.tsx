import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ArrowLeft, Scale, Truck, FileText, Layers,
  ShieldCheck, CheckCircle2, XCircle, AlertCircle, Clock,
} from 'lucide-react';
import { TopBar } from '@/components/layout/TopBar';
import { Footer } from '@/components/layout/Footer';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { RiskScore } from '@/components/ui/RiskScore';
import { VerificationFlags } from '@/components/verification/VerificationFlags';
import { ExplainabilityBreakdown } from '@/components/verification/ExplainabilityBreakdown';
import { MassBalancePanel } from '@/components/verification/MassBalancePanel';
import { EvidencePanel, getMissingRequiredEvidence } from '@/components/claims/EvidencePanel';
import { AuditTimeline, MassBalanceAdjustments } from '@/components/claims/AuditAndAdjustments';
import { dismissVerificationFlag, fetchClaim, govApproveClaim, govRejectClaim, govRequestClaimClarification, govRecordAuditNote } from '@/lib/api';
import { claimStatusConfig, formatDate, formatWeight } from '@/lib/utils';
import { useAuth } from '@/lib/auth';
import type { RecyclingClaim } from '@/types';

type Tab = 'flags' | 'mass_balance' | 'transport' | 'explainability';

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'flags',          label: 'Flags',          icon: ShieldCheck },
  { id: 'mass_balance',   label: 'Mass Balance',   icon: Scale       },
  { id: 'transport',      label: 'Transport',      icon: Truck       },
  { id: 'explainability', label: 'Explainability', icon: Layers      },
];

function RejectModal({
  onConfirm,
  onCancel,
  loading,
}: {
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 animate-fade-in">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-full bg-red-50 flex items-center justify-center shrink-0">
            <XCircle className="h-5 w-5 text-red-600" aria-hidden="true" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900">Reject this claim</p>
            <p className="text-xs text-slate-500">Provide a reason. This will be visible to the producer.</p>
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold text-slate-700">
            Rejection reason <span className="text-red-500">*</span>
          </label>
          <textarea
            rows={3}
            value={reason}
            onChange={e => { setReason(e.target.value); setErr(''); }}
            placeholder="e.g. Output mass exceeds declared input. Please resubmit with corrected weighbridge data."
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent resize-none"
          />
          {err && (
            <p className="flex items-center gap-1 text-xs text-red-600" role="alert">
              <AlertCircle className="h-3 w-3" aria-hidden="true" />{err}
            </p>
          )}
        </div>

        <div className="flex gap-2 justify-end">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button
            variant="danger"
            size="sm"
            loading={loading}
            onClick={() => {
              if (!reason.trim()) { setErr('Reason is required.'); return; }
              onConfirm(reason.trim());
            }}
          >
            Confirm Rejection
          </Button>
        </div>
      </div>
    </div>
  );
}

function GovClaimDetailPageContent() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [claim, setClaim]           = useState<RecyclingClaim | null>(null);
  const [claimLoading, setClaimLoading] = useState(true);
  const [claimLoadError, setClaimLoadError] = useState('');
  const [tab, setTab]               = useState<Tab>('flags');
  const [approving, setApproving]   = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [rejecting, setRejecting]   = useState(false);
  const [clarificationReason, setClarificationReason] = useState('');
  const [requestingClarification, setRequestingClarification] = useState(false);
  const [auditNote, setAuditNote] = useState('');
  const [auditType, setAuditType] = useState<'ROUTINE' | 'INVESTIGATION'>('ROUTINE');
  const [savingAuditNote, setSavingAuditNote] = useState(false);
  const [actionMsg, setActionMsg]   = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const reload = async () => {
    if (!id) {
      setClaimLoadError('The claim link is missing an ID. Return to the claims list and open it again.');
      setClaimLoading(false);
      return;
    }
    setClaimLoading(true);
    setClaimLoadError('');
    try {
      setClaim(await fetchClaim(id));
    } catch (error) {
      setClaim(null);
      setClaimLoadError(error instanceof Error ? error.message : 'We could not load this claim.');
    } finally {
      setClaimLoading(false);
    }
  };

  useEffect(() => { void reload(); }, [id]);

  const handleApprove = async () => {
    if (!claim || !user) return;
    setApproving(true);
    setActionMsg(null);
    try {
      const updated = await govApproveClaim(claim.id, user.name);
      setClaim(updated);
      setActionMsg({ type: 'success', text: `Claim approved by ${user.name}.` });
    } finally {
      setApproving(false);
    }
  };

  const handleReject = async (reason: string) => {
    if (!claim || !user) return;
    setRejecting(true);
    try {
      const updated = await govRejectClaim(claim.id, user.name, reason);
      setClaim(updated);
      setShowReject(false);
      setActionMsg({ type: 'error', text: `Claim rejected. Reason recorded.` });
    } finally {
      setRejecting(false);
    }
  };

  const handleClarification = async (reason = clarificationReason) => {
    if (!claim || !reason.trim()) return;
    setRequestingClarification(true);
    setActionMsg(null);
    try {
      const updated = await govRequestClaimClarification(claim.id, reason.trim());
      setClaim(updated);
      setActionMsg({ type: 'success', text: 'Clarification requested and recorded in the audit history.' });
      setClarificationReason('');
    } catch (requestError) {
      setActionMsg({ type: 'error', text: requestError instanceof Error ? requestError.message : 'Could not request clarification.' });
    } finally {
      setRequestingClarification(false);
    }
  };

  const handleAuditNote = async () => {
    if (!claim || !auditNote.trim()) return;
    setSavingAuditNote(true);
    setActionMsg(null);
    try {
      const updated = await govRecordAuditNote(claim.id, auditType, auditNote.trim());
      setClaim(updated);
      setAuditNote('');
      setActionMsg({ type: 'success', text: `${auditType === 'ROUTINE' ? 'Routine audit' : 'Investigation'} note recorded.` });
    } catch (requestError) {
      setActionMsg({ type: 'error', text: requestError instanceof Error ? requestError.message : 'Could not record the audit note.' });
    } finally {
      setSavingAuditNote(false);
    }
  };

  const handleDismissFlag = async (flag: NonNullable<RecyclingClaim['verification_result']>['flags'][number]) => {
    if (!claim || !flag.flag_id) return;
    const reason = window.prompt('Record why this finding is dismissed (at least five characters).');
    if (!reason?.trim()) return;
    try {
      setClaim(await dismissVerificationFlag(claim.id, flag.flag_id, reason.trim()));
      setActionMsg({ type: 'success', text: 'Finding dismissed. The rationale and updated score were recorded.' });
    } catch (error) {
      setActionMsg({ type: 'error', text: error instanceof Error ? error.message : 'Could not dismiss this finding.' });
    }
  };

  if (!claim) return (
    <div className="flex flex-col min-h-full">
      <TopBar title="Claim Detail" />
      <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
        {claimLoading ? <p className="text-sm text-slate-500">Loading claim…</p> : <>
          <p className="text-sm font-medium text-slate-800">Unable to open this claim</p>
          <p className="max-w-lg text-sm text-slate-600" role="alert">{claimLoadError || 'This claim is unavailable to your account. It may not be assigned to your jurisdiction.'}</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => void reload()}>Try again</Button>
            <Link to="/gov/claims"><Button size="sm">Back to claims</Button></Link>
          </div>
        </>}
      </div>
      <Footer />
    </div>
  );

  const vr = claim.verification_result;
  const activeFlags = (vr?.flags ?? []).filter(flag => flag.status !== 'RESOLVED' && flag.status !== 'DISMISSED');
  const sc = claimStatusConfig(claim.status);
  const isPending  = claim.status === 'PENDING' || claim.status === 'FLAGGED';
  const isVerified = claim.status === 'APPROVED' || claim.status === 'VERIFIED';
  const isRejected = claim.status === 'REJECTED';
  const missingDocuments = getMissingRequiredEvidence(claim.evidence, claim.received_at, claim.processing_completed_at);
  const missingDocumentsRequest = `Please upload the following missing required documents for claim ${claim.reference_number}: ${missingDocuments.join(', ')}.`;

  return (
    <>
      {showReject && (
        <RejectModal
          onConfirm={handleReject}
          onCancel={() => setShowReject(false)}
          loading={rejecting}
        />
      )}

      <div className="flex flex-col min-h-full">
        <TopBar title={claim.reference_number} subtitle={claim.waste_category} />
        <div className="flex-1 p-6 space-y-5 animate-fade-in">

          {/* Header row */}
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3">
              <Link to="/gov/claims">
                <Button variant="ghost" size="sm">
                  <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Claims
                </Button>
              </Link>
              <Badge className={`${sc.bg} ${sc.text} text-sm px-3 py-1`}>{sc.label}</Badge>
            </div>
            <Button variant="secondary" size="sm">
              <FileText className="h-4 w-4" aria-hidden="true" /> Export Report
            </Button>
          </div>

          {/* Action feedback banner */}
          {actionMsg && (
            <div className={`flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium ${
              actionMsg.type === 'success'
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                : 'bg-red-50 text-red-700 border border-red-200'
            }`} role="status">
              {actionMsg.type === 'success'
                ? <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                : <XCircle className="h-4 w-4" aria-hidden="true" />
              }
              {actionMsg.text}
            </div>
          )}

          <EvidencePanel
            claimId={claim.id}
            claim={claim}
            evidence={claim.evidence}
            status={claim.status}
            receivedAt={claim.received_at}
            processingCompletedAt={claim.processing_completed_at}
            party="AUDITOR"
          />

          <Card>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-500">Transaction Trail</h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-[10px] font-semibold uppercase text-slate-500">Producer Declaration</p>
                <p className="mt-1 text-sm font-semibold">{formatWeight(claim.mass_balance.declared_input_kg)}</p>
                <p className="text-[10px] text-slate-500">{claim.producer.name}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-[10px] font-semibold uppercase text-slate-500">Recycler Confirmation</p>
                <p className="mt-1 text-sm font-semibold">{claim.mass_balance.received_input_kg === null ? 'Awaiting receipt' : formatWeight(claim.mass_balance.received_input_kg)}</p>
                <p className="text-[10px] text-slate-500">{claim.received_at ? formatDate(claim.received_at) : claim.recycler.name}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-[10px] font-semibold uppercase text-slate-500">Processing Results</p>
                <p className="mt-1 text-sm font-semibold">{claim.mass_balance.processed_output_kg === null ? 'Not submitted' : formatWeight(claim.mass_balance.processed_output_kg)}</p>
                <p className="text-[10px] text-slate-500">Processing date: {claim.processing_date || '—'}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-[10px] font-semibold uppercase text-slate-500">ChainGuard Verification</p>
                <p className="mt-1 text-sm font-semibold">{vr ? `${activeFlags.length} active finding(s)` : 'Waiting for processing'}</p>
                <p className="text-[10px] text-slate-500">{vr ? formatDate(vr.verified_at) : '—'}</p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-[10px] font-semibold uppercase text-slate-500">Risk / Decision</p>
                <p className="mt-1 text-sm font-semibold">{vr ? `${vr.risk_score} · ${vr.risk_level}` : 'Not scored'}</p>
                <p className="text-[10px] text-slate-500">{isVerified ? 'Approved' : isRejected ? 'Rejected' : 'Awaiting review'}</p>
              </div>
            </div>
          </Card>

          {claim.processing_batches?.length ? <Card>
            <h2 className="mb-3 text-xs font-bold uppercase tracking-wide text-slate-500">Recycler Processing</h2>
            <div className="space-y-2">
              {claim.processing_batches?.map(batch => <div key={batch.batch_id} className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
                <p className="font-semibold text-slate-800">{batch.batch_id} · {formatWeight(batch.processed_output_kg)} processed</p>
                <p>Recovered {formatWeight(batch.recovered_materials.reduce((sum, item) => sum + item.quantity_kg, 0))} · Residual {formatWeight(batch.residual_waste_kg)} · {batch.processing_date}</p>
                <p>Submitted by {batch.submitted_by.name} ({batch.submitted_by.organisation}) · {formatDate(batch.submitted_at)}</p>
                {batch.notes && <p className="mt-1 whitespace-pre-line">Batch notes: {batch.notes}</p>}
              </div>)}
              {claim.recycler_notes && <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">Recycler receipt / processing notes: {claim.recycler_notes}</p>}
            </div>
          </Card> : null}
          <MassBalanceAdjustments claim={claim} allowReview onUpdated={setClaim} />
          <AuditTimeline events={claim.audit_events} chainValid={claim.audit_chain_valid} />

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            {/* Main content */}
            <div className="lg:col-span-2 space-y-5">
              {/* Parties */}
              <Card>
                <div className="grid grid-cols-2 gap-4">
                  {[{ label: 'Producer', org: claim.producer }, { label: 'Recycler', org: claim.recycler }].map(({ label, org }) => (
                    <div key={label}>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">{label}</p>
                      <p className="text-sm font-semibold text-slate-800">{org.name}</p>
                      <p className="text-xs text-slate-500">{org.registration_number}</p>
                      <p className="text-xs text-slate-500">{org.city}</p>
                    </div>
                  ))}
                </div>
                {claim.notes && (
                  <div className="mt-3 pt-3 border-t border-slate-100">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 mb-1">Notes</p>
                    <p className="text-xs text-slate-600 whitespace-pre-line">{claim.notes}</p>
                  </div>
                )}
              </Card>

              {/* Tab panel */}
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
                      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="hidden sm:inline">{label}</span>
                    </button>
                  ))}
                </nav>

                <Card>
                  {tab === 'flags' && (vr
                    ? <VerificationFlags flags={vr.flags} onDismiss={handleDismissFlag} />
                    : <p className="text-sm text-slate-500 text-center py-8">No verification result.</p>
                  )}
                  {tab === 'mass_balance' && <MassBalancePanel balance={claim.mass_balance} />}
                  {tab === 'transport' && (
                    <div className="space-y-4">
                      {claim.transport.map((leg, i) => (
                        <div key={i} className="rounded-lg border border-slate-200 p-4 space-y-2">
                          <p className="font-mono text-sm font-semibold text-slate-800">
                            {leg.vehicle_registration} · {leg.driver_name}
                          </p>
                          <div className="grid grid-cols-2 gap-2 text-xs text-slate-600">
                            <span>Departed: {formatDate(leg.departed_at)}</span>
                            <span>Expected arrival (producer): {formatDate(leg.arrived_at)}</span>
                            <span>Declared: {formatWeight(leg.declared_weight_kg)}</span>
                            <span>Received: {leg.actual_weight_kg ? formatWeight(leg.actual_weight_kg) : '—'}</span>
                            <span>Origin: {leg.origin.lat.toFixed(4)}, {leg.origin.lng.toFixed(4)}</span>
                            <span>Dest: {leg.destination.lat.toFixed(4)}, {leg.destination.lng.toFixed(4)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  {tab === 'explainability' && (vr
                    ? <ExplainabilityBreakdown data={vr.explainability} />
                    : <p className="text-sm text-slate-500 text-center py-8">No explainability data.</p>
                  )}
                </Card>
              </div>
            </div>

            {/* Right sidebar */}
            <aside className="space-y-4">
              {/* Risk score */}
              {vr ? (
                <Card>
                  <div className="flex flex-col items-center gap-3 py-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Risk Score</p>
                    <RiskScore score={vr.risk_score} level={vr.risk_level} size="lg" />
                    <p className="text-center text-[10px] text-slate-500">
                      {vr.risk_level === 'LOW' ? 'No discrepancies found' :
                       vr.risk_level === 'MEDIUM' ? 'A few discrepancies; review recommended' :
                       vr.risk_level === 'HIGH' ? 'Multiple discrepancies; careful review recommended' :
                       'Critical discrepancy requires review'}
                    </p>
                    <div className="w-full mt-2 space-y-1.5">
                      {[
                        { label: 'Active findings', value: activeFlags.length },
                        { label: 'Critical findings', value: activeFlags.filter(f => f.severity === 'CRITICAL').length },
                        { label: 'Analysed at',    value: formatDate(vr.verified_at) },
                        { label: 'Engine',         value: vr.model_version },
                        { label: 'Rule set', value: vr.explainability.score_history?.slice(-1)[0]?.ruleset_version ?? 'risk-rules-v3.0.0' },
                      ].map(({ label, value }) => (
                        <div key={label} className="flex justify-between text-xs">
                          <span className="text-slate-500">{label}</span>
                          <span className="font-medium text-slate-800">{value}</span>
                        </div>
                      ))}
                    </div>
                    {(vr.explainability.score_history?.length ?? 0) > 1 && <div className="w-full border-t border-slate-100 pt-2">
                      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Score history</p>
                      <ol className="space-y-1">
                        {vr.explainability.score_history?.slice(-5).reverse().map((snapshot, index) => <li key={`${snapshot.calculated_at}-${index}`} className="flex items-center justify-between gap-2 text-[10px] text-slate-600">
                          <span>{formatDate(snapshot.calculated_at)}</span><span className="font-medium">{snapshot.score} · {snapshot.risk_band}</span>
                        </li>)}
                      </ol>
                    </div>}
                  </div>
                </Card>
              ) : (
                <Card>
                  <p className="text-sm text-slate-500 text-center py-6">No risk analysis yet.</p>
                </Card>
              )}

              {/* Auditor decision panel */}
              <Card>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-3">
                  Official Decision
                </p>

                {isPending && (
                  <div className="space-y-2">
                    <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 flex items-center gap-2 mb-3">
                      <Clock className="h-4 w-4 text-amber-500 shrink-0" aria-hidden="true" />
                      <p className="text-xs text-amber-700 font-medium">
                        Awaiting your decision. Review the risk score and flags before approving.
                      </p>
                    </div>
                    <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                      <p className="text-xs font-semibold text-amber-900">Missing required documents</p>
                      {missingDocuments.length ? (
                        <>
                          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-amber-800">
                            {missingDocuments.map(document => <li key={document}>{document}</li>)}
                          </ul>
                          <Button variant="secondary" size="sm" className="mt-2 w-full justify-center" loading={requestingClarification}
                            onClick={() => void handleClarification(missingDocumentsRequest)}>
                            Request Missing Documents
                          </Button>
                        </>
                      ) : <p className="mt-1 text-xs text-emerald-700">All required documents due at this stage are attached.</p>}
                    </div>
                    <label className="block space-y-1 text-xs font-medium text-slate-600">
                      Request clarification
                      <textarea rows={2} value={clarificationReason} onChange={event => setClarificationReason(event.target.value)} placeholder="Describe the correction or missing information needed" className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
                    </label>
                    <Button variant="secondary" size="sm" className="w-full justify-center" loading={requestingClarification} disabled={!clarificationReason.trim()} onClick={handleClarification}>Request Clarification</Button>
                    <Button
                      className="w-full justify-center bg-emerald-600 hover:bg-emerald-700 text-white"
                      size="sm"
                      loading={approving}
                      onClick={handleApprove}
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      Approve Claim
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      className="w-full justify-center"
                      onClick={() => setShowReject(true)}
                    >
                      <XCircle className="h-4 w-4" aria-hidden="true" />
                      Reject Claim
                    </Button>
                  </div>
                )}

                <div className="mt-4 border-t border-slate-100 pt-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Record an Audit</p>
                  <select value={auditType} onChange={event => setAuditType(event.target.value as 'ROUTINE' | 'INVESTIGATION')} className="mb-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs">
                    <option value="ROUTINE">Routine audit</option>
                    <option value="INVESTIGATION">Investigation note</option>
                  </select>
                  <textarea rows={2} value={auditNote} onChange={event => setAuditNote(event.target.value)} placeholder="Record what was reviewed or investigated" className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" />
                  <Button variant="secondary" size="sm" className="mt-2 w-full justify-center" loading={savingAuditNote} disabled={!auditNote.trim()} onClick={handleAuditNote}>Save Audit Note</Button>
                </div>

                {claim.status === 'AWAITING_CLARIFICATION' && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">Awaiting recycler response: {claim.clarification_reason}</p>}

                {isVerified && (
                  <div className="flex flex-col items-center gap-2 py-3">
                    <div className="h-10 w-10 rounded-full bg-emerald-50 flex items-center justify-center">
                      <CheckCircle2 className="h-5 w-5 text-emerald-600" aria-hidden="true" />
                    </div>
                    <p className="text-sm font-semibold text-emerald-700">Claim Approved</p>
                    <p className="text-xs text-slate-500 text-center">
                      Approved on {formatDate(claim.updated_at)}
                    </p>
                  </div>
                )}

                {isRejected && (
                  <div className="flex flex-col items-center gap-2 py-3">
                    <div className="h-10 w-10 rounded-full bg-red-50 flex items-center justify-center">
                      <XCircle className="h-5 w-5 text-red-600" aria-hidden="true" />
                    </div>
                    <p className="text-sm font-semibold text-red-700">Claim Rejected</p>
                    <p className="text-xs text-slate-500 text-center">
                      Rejected on {formatDate(claim.updated_at)}
                    </p>
                  </div>
                )}
              </Card>
            </aside>
          </div>
        </div>
        <Footer />
      </div>
    </>
  );
}

/** Keep a malformed legacy record or unexpected API shape from blanking the officer workspace. */
class GovClaimDetailErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Government claim detail failed to render', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-full flex-col">
          <TopBar title="Claim Detail" />
          <main className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-sm font-medium text-slate-800">This claim could not be displayed</p>
            <p className="max-w-lg text-sm text-slate-600">The claim data contains a field this page could not display. Return to the claims list and try again, or report this claim reference to support.</p>
            <Link to="/gov/claims"><Button>Back to claims</Button></Link>
          </main>
          <Footer />
        </div>
      );
    }
    return this.props.children;
  }
}

export function GovClaimDetailPage() {
  return <GovClaimDetailErrorBoundary><GovClaimDetailPageContent /></GovClaimDetailErrorBoundary>;
}
