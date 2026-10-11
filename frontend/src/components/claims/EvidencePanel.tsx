import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Archive, CheckCircle2, Clock3, Download, ExternalLink, FileText, History, RefreshCw, ShieldAlert, Upload, XCircle } from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { openEvidenceFile, uploadClaimEvidence, replaceClaimEvidence, fetchEvidenceVersions, archiveClaimEvidence, downloadEvidenceFile } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import type { ClaimStatus, EvidenceFile, EvidenceVersionHistory, RecyclingClaim } from '@/types';

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const ACCEPTED_FORMATS = 'PDF, JPG, JPEG, PNG, WEBP · up to 10 MB';

const CHECKLIST = [
  {
    id: 'COLLECTION_WEIGHT_SLIP',
    title: 'Collection / Origin Weight Slip',
    purpose: 'Supports the producer-declared collection weight at origin.',
    responsible: 'Producer / Collector',
    checks: ['Document quantity consistency', 'Declared-to-received mass reconciliation'],
  },
  {
    id: 'TRANSPORT_CHALLAN',
    title: 'Transport Challan / Delivery Note',
    purpose: 'Supports the shipment, vehicle, route, and delivery handover.',
    responsible: 'Producer / Collector',
    checks: ['Transport route and timeline checks', 'Party consistency'],
  },
  {
    id: 'RECYCLER_RECEIPT',
    title: 'Recycler Receipt / Destination Weight Slip',
    purpose: 'Supports the recycler-confirmed receipt date and received weight.',
    responsible: 'Assigned Recycler',
    checks: ['Declared-to-received mass reconciliation', 'Recycler receipt document consistency'],
  },
  {
    id: 'PROCESSING_RECOVERY',
    title: 'Processing & Recovery Record',
    purpose: 'Supports processing output, recovered materials, and residual waste.',
    responsible: 'Assigned Recycler',
    checks: ['Processed-output mass balance', 'Recovered plus residual reconciliation'],
  },
  {
    id: 'RECYCLING_CERTIFICATE',
    title: 'Recycling Certificate',
    purpose: 'Supports the final recycling outcome and certificate identifiers.',
    responsible: 'Assigned Recycler',
    checks: ['Certificate identifier and entity consistency', 'Duplicate evidence checks'],
  },
  {
    id: 'OTHER_SUPPORTING',
    title: 'Other Supporting Evidence',
    purpose: 'Additional documents relevant to this claim; not a substitute for required records.',
    responsible: 'Producer / Collector or Recycler',
    checks: ['Document consistency when structured data is supplied', 'Exact duplicate file check'],
  },
] as const;

type Category = EvidenceFile['category'];
type Party = 'PRODUCER' | 'RECYCLER' | 'AUDITOR';

const STATUS_STYLE: Record<string, { label: string; className: string; icon: typeof Clock3 }> = {
  PENDING: { label: 'Pending checks', className: 'bg-slate-100 text-slate-700', icon: Clock3 },
  METADATA_PROVIDED: { label: 'Uploader metadata · unverified', className: 'bg-blue-50 text-blue-800', icon: AlertTriangle },
  EXTRACTED_UNVERIFIED: { label: 'Fields extracted · unverified', className: 'bg-blue-50 text-blue-800', icon: AlertTriangle },
  METADATA_CONSISTENT: { label: 'Metadata consistent', className: 'bg-emerald-50 text-emerald-700', icon: CheckCircle2 },
  DISCREPANCY_DETECTED: { label: 'Discrepancy detected', className: 'bg-red-50 text-red-700', icon: ShieldAlert },
  PENDING_HUMAN_REVIEW: { label: 'Pending human review', className: 'bg-amber-50 text-amber-800', icon: Clock3 },
  MANUAL_REVIEW: { label: 'Manual review required', className: 'bg-amber-50 text-amber-800', icon: Clock3 },
  HUMAN_VERIFIED: { label: 'Human reviewed', className: 'bg-emerald-50 text-emerald-700', icon: CheckCircle2 },
  UNAVAILABLE: { label: 'File unavailable', className: 'bg-red-50 text-red-700', icon: XCircle },
};

const EVIDENCE_STATUS_STYLE: Record<string, { label: string; className: string }> = {
  ACTIVE: { label: 'Active', className: 'bg-emerald-50 text-emerald-700' },
  SUPERSEDED: { label: 'Superseded', className: 'bg-slate-100 text-slate-500' },
  ARCHIVED: { label: 'Archived', className: 'bg-orange-50 text-orange-700' },
  PENDING_REVIEW: { label: 'Pending review', className: 'bg-purple-50 text-purple-700' },
};

function isDue(category: Category, receivedAt: string | null, processedAt: string | null) {
  if (category === 'RECYCLER_RECEIPT') return Boolean(receivedAt);
  if (category === 'PROCESSING_RECOVERY' || category === 'RECYCLING_CERTIFICATE') return Boolean(processedAt);
  return true;
}

function requiredLabel(category: Category, due: boolean) {
  if (category === 'OTHER_SUPPORTING') return 'Optional';
  if (category === 'RECYCLING_CERTIFICATE') return due ? 'Conditional · after processing' : 'Conditional · after processing';
  if (!due) return 'Required at a later stage';
  return 'Required for this stage';
}

export function getMissingRequiredEvidence(
  evidence: EvidenceFile[],
  receivedAt: string | null | undefined,
  processingCompletedAt: string | null | undefined,
) {
  return CHECKLIST.filter(card => {
    const category = card.id as Category;
    const required = category !== 'OTHER_SUPPORTING' && category !== 'RECYCLING_CERTIFICATE';
    if (!required || !isDue(category, receivedAt ?? null, processingCompletedAt ?? null)) return false;
    return !evidence.some(item => item.category === category
      && (item.status === 'ACTIVE' || item.status === 'PENDING_REVIEW' || !item.status));
  }).map(card => card.title);
}

function compareExtractedFields(item: EvidenceFile, claim?: RecyclingClaim) {
  if (!item.extracted_data || !claim) return null;
  const data = item.extracted_data;
  const recyclerDoc = item.source === 'RECYCLER';
  const quantityTarget = item.category === 'RECYCLER_RECEIPT' || (recyclerDoc && item.category === 'PROCESSING_RECOVERY')
    ? claim.mass_balance.received_input_kg
    : claim.mass_balance.declared_input_kg;
  const dateTarget = item.category === 'PROCESSING_RECOVERY'
    ? claim.processing_date || claim.processing_completed_at
    : item.category === 'RECYCLER_RECEIPT'
      ? claim.received_at
      : claim.collection_date;
  const material = [claim.waste_category.split(/[—–]/).slice(-1)[0].trim(), ...claim.waste_subcategories].filter(Boolean).join(' ');
  const expected: Record<string, string | number | null | undefined> = {
    producer: claim.producer.name,
    recycler: claim.recycler.name,
    facility: claim.recycler.name,
    transporter: undefined,
    claim_reference: claim.reference_number,
    quantity_unit: 'kg',
    material_type: material,
    vehicle_registration: claim.transport[0]?.vehicle_registration,
    date: dateTarget,
    dispatch_date: claim.collection_date,
    arrival_date: claim.received_at,
    quantity: quantityTarget,
    net_weight_kg: quantityTarget,
    received_quantity_kg: claim.mass_balance.received_input_kg,
    processing_input_kg: claim.mass_balance.received_input_kg,
    recovered_quantity_kg: claim.mass_balance.recovered_materials.reduce((sum, value) => sum + value.quantity_kg, 0),
    residual_quantity_kg: claim.mass_balance.residual_waste_kg,
  };
  const quantityFields = new Set(['quantity', 'net_weight_kg', 'received_quantity_kg', 'processing_input_kg', 'recovered_quantity_kg', 'residual_quantity_kg']);
  const normalizeText = (value: unknown) => String(value ?? '').normalize('NFKD').replace(/[^\p{L}\p{N}]/gu, '').toLocaleLowerCase();
  return Object.entries(data).filter(([key, value]) => key !== '_provenance' && value !== null && value !== undefined && expected[key] !== undefined)
    .map(([key, value]) => {
      const entered = expected[key];
      let result: 'MATCH' | 'MISMATCH' | 'NOT_ENTERED' = 'NOT_ENTERED';
      if (entered !== null && entered !== undefined && entered !== '') {
        const documentValue = key === 'quantity'
          && String(data.quantity_unit || '').toLowerCase() === 'tonnes'
          ? Number(value) * 1000
          : value;
        if (quantityFields.has(key) && typeof documentValue === 'number' && typeof entered === 'number') {
          result = Math.abs(documentValue - entered) / Math.max(Math.abs(entered), 1) <= 0.05 ? 'MATCH' : 'MISMATCH';
        } else if (key.endsWith('date') || key === 'date') {
          const docDate = Date.parse(String(documentValue));
          const claimDate = Date.parse(String(entered));
          result = Number.isFinite(docDate) && Number.isFinite(claimDate)
            ? Math.abs(docDate - claimDate) <= 24 * 60 * 60 * 1000 ? 'MATCH' : 'MISMATCH'
            : normalizeText(documentValue) === normalizeText(entered) ? 'MATCH' : 'MISMATCH';
        } else {
          const docText = normalizeText(documentValue);
          const enteredText = normalizeText(entered);
          result = docText === enteredText || (key === 'material_type' && docText.length > 0 && enteredText.length > 0
            && (docText.includes(enteredText) || enteredText.includes(docText)))
            ? 'MATCH'
            : 'MISMATCH';
        }
      }
      return { key, value, entered, result };
    });
}

export function EvidencePanel({
  claimId,
  evidence,
  claim,
  status,
  receivedAt = null,
  processingCompletedAt = null,
  party,
  onClaimUpdated,
}: {
  claimId: string;
  evidence: EvidenceFile[];
  claim?: RecyclingClaim;
  status: ClaimStatus;
  receivedAt?: string | null;
  processingCompletedAt?: string | null;
  party: Party;
  onClaimUpdated?: (claim: RecyclingClaim) => void;
}) {
  const [items, setItems] = useState(evidence);
  const [selected, setSelected] = useState<Partial<Record<Category, File>>>({});
  const evidenceInputRefs = useRef<Partial<Record<Category, HTMLInputElement | null>>>({});
  const [structuredFiles, setStructuredFiles] = useState<Partial<Record<Category, File>>>({});
  const [linkedTypes, setLinkedTypes] = useState<Partial<Record<Category, string>>>({});
  const [linkedIds, setLinkedIds] = useState<Partial<Record<Category, string>>>({});
  const [uploading, setUploading] = useState<Category | null>(null);
  const [messages, setMessages] = useState<Partial<Record<Category, string>>>({});
  const [replaceTarget, setReplaceTarget] = useState<string | null>(null);
  const [replaceFile, setReplaceFile] = useState<File | null>(null);
  const [replaceReason, setReplaceReason] = useState('');
  const [replacing, setReplacing] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<string | null>(null);
  const [archiveReason, setArchiveReason] = useState('');
  const [archiving, setArchiving] = useState(false);
  const [versionHistory, setVersionHistory] = useState<EvidenceVersionHistory | null>(null);
  const [versionLoading, setVersionLoading] = useState(false);

  useEffect(() => setItems(evidence), [evidence]);

  const finalDecision = ['APPROVED', 'VERIFIED', 'REJECTED'].includes(status);
  const canUploadCategory = (category: Category, due: boolean) => {
    if (party === 'AUDITOR' || finalDecision || !due) return false;
    if (category === 'COLLECTION_WEIGHT_SLIP' || category === 'TRANSPORT_CHALLAN') {
      return party === 'PRODUCER' && status === 'AWAITING_RECYCLER_CONFIRMATION';
    }
    if (category === 'RECYCLER_RECEIPT') return party === 'RECYCLER' && Boolean(receivedAt);
    if (category === 'PROCESSING_RECOVERY' || category === 'RECYCLING_CERTIFICATE') {
      return party === 'RECYCLER' && Boolean(processingCompletedAt);
    }
    return party === 'RECYCLER'
      ? Boolean(receivedAt)
      : status === 'AWAITING_RECYCLER_CONFIRMATION';
  };

  const canReplace = (item: EvidenceFile) => {
    if (party === 'AUDITOR' || status === 'REJECTED') return false;
    if (finalDecision && party !== 'RECYCLER') return false;
    if (item.status !== 'ACTIVE') return false;
    if (party === 'PRODUCER') return status === 'AWAITING_RECYCLER_CONFIRMATION';
    return party === 'RECYCLER';
  };

  const canArchive = (item: EvidenceFile) => {
    if (party === 'AUDITOR' || finalDecision) return false;
    return item.status === 'ACTIVE';
  };

  const upload = async (category: Category) => {
    const file = selected[category];
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setMessages(current => ({ ...current, [category]: 'File exceeds the 10 MB limit.' }));
      return;
    }
    setUploading(category);
    setMessages(current => ({ ...current, [category]: '' }));
    try {
      const structuredFile = structuredFiles[category];
      const structuredData = structuredFile ? await structuredFile.text() : undefined;
      const linkedType = linkedTypes[category] || 'CLAIM';
      const linkedId = linkedType === 'CLAIM' || linkedType === 'RECEIPT' || linkedType === 'RESIDUAL_WASTE'
        ? claimId : linkedIds[category];
      if (!linkedId) {
        setMessages(current => ({ ...current, [category]: 'Enter the linked transport leg or processing batch ID.' }));
        return;
      }
      const updated = await uploadClaimEvidence(claimId, file, category, structuredData, linkedType, linkedId);
      setItems(updated.evidence);
      onClaimUpdated?.(updated);
      setSelected(current => ({ ...current, [category]: undefined }));
      setStructuredFiles(current => ({ ...current, [category]: undefined }));
      setMessages(current => ({ ...current, [category]: 'Evidence uploaded and linked to this claim.' }));
    } catch (error) {
      setMessages(current => ({ ...current, [category]: error instanceof Error ? error.message : 'Upload failed.' }));
    } finally {
      setUploading(null);
    }
  };

  const handleReplace = async () => {
    if (!replaceTarget || !replaceFile || replaceReason.trim().length < 3) return;
    setReplacing(true);
    try {
      const updated = await replaceClaimEvidence(claimId, replaceTarget, replaceFile, replaceReason);
      setItems(updated.evidence);
      onClaimUpdated?.(updated);
      setReplaceTarget(null);
      setReplaceFile(null);
      setReplaceReason('');
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Replace failed');
    } finally {
      setReplacing(false);
    }
  };

  const handleArchive = async () => {
    if (!archiveTarget || archiveReason.trim().length < 3) return;
    setArchiving(true);
    try {
      const updated = await archiveClaimEvidence(claimId, archiveTarget, archiveReason);
      setItems(updated.evidence);
      onClaimUpdated?.(updated);
      setArchiveTarget(null);
      setArchiveReason('');
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Archive failed');
    } finally {
      setArchiving(false);
    }
  };

  const loadVersions = async (evidenceId: string) => {
    setVersionLoading(true);
    try {
      const history = await fetchEvidenceVersions(claimId, evidenceId);
      setVersionHistory(history);
    } catch {
      setVersionHistory(null);
    } finally {
      setVersionLoading(false);
    }
  };

  const handleDownload = async (evidenceId: string, filename: string) => {
    try {
      const blob = await downloadEvidenceFile(claimId, evidenceId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Download failed');
    }
  };

  return (
    <Card>
      <div className="space-y-4">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">{party === 'RECYCLER' ? 'Claim documents' : 'Evidence Checklist'}</h2>
          {party !== 'RECYCLER' && <p className="mt-1 text-xs text-slate-500">Missing evidence is a completeness reminder. It does not by itself indicate fraud or add risk.</p>}
          {party !== 'RECYCLER' && <p className="mt-1 text-[10px] text-slate-400">Accepted formats: {ACCEPTED_FORMATS}</p>}
        </div>

        <div className="grid gap-3">
          {CHECKLIST.map(card => {
            const category = card.id as Category;
            const due = isDue(category, receivedAt, processingCompletedAt);
            const attached = items.filter(item => item.category === category);
            const activeAttached = attached.filter(item => item.status === 'ACTIVE' || item.status === 'PENDING_REVIEW' || !item.status);
            const supersededAttached = attached.filter(item => item.status === 'SUPERSEDED');
            const archivedAttached = attached.filter(item => item.status === 'ARCHIVED');
            const required = category !== 'OTHER_SUPPORTING' && category !== 'RECYCLING_CERTIFICATE';
            const stageLabel = requiredLabel(category, due);
            const uploadable = canUploadCategory(category, due);
            const uploadDisabledReason = !due
              ? category === 'RECYCLER_RECEIPT'
                ? 'Upload area opens after the recycler confirms receipt.'
                : 'Upload area opens after processing is completed.'
              : category === 'COLLECTION_WEIGHT_SLIP' || category === 'TRANSPORT_CHALLAN'
                ? party !== 'PRODUCER'
                  ? 'Producer / Collector uploads this document.'
                  : 'Producer uploads close after recycler confirmation.'
                : category === 'OTHER_SUPPORTING'
                  ? party === 'PRODUCER'
                    ? 'Producer supporting files can be added before recycler confirmation.'
                    : 'Available to the assigned recycler after receipt.'
                  : 'Only the assigned recycler can upload this document.';
            const emptyState = !due
              ? 'Not required yet — this document belongs to a later stage.'
              : required && !activeAttached.length
                ? 'Missing for this stage.'
                : category === 'RECYCLING_CERTIFICATE' && !activeAttached.length
                  ? 'Conditional; provide when applicable.'
                  : 'No file uploaded; optional.';

            return (
              <details key={category} open={party !== 'RECYCLER'} className="rounded-lg border border-slate-200 p-3">
                <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-slate-800">{card.title}</h3>
                    {party !== 'RECYCLER' && <><p className="mt-1 text-xs text-slate-500">{card.purpose}</p><p className="mt-1 text-[10px] text-slate-400">Responsible: {card.responsible} · {stageLabel}</p></>}
                  </div>
                  <div className="ml-auto flex shrink-0 items-center gap-2">
                    <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${activeAttached.length ? 'bg-teal-50 text-teal-700' : due && required ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-600'}`}>
                      {activeAttached.length ? `${activeAttached.length} file${activeAttached.length === 1 ? '' : 's'}` : due && required ? 'Missing' : !due ? 'Later stage' : category === 'RECYCLING_CERTIFICATE' ? 'Conditional' : 'Optional'}
                      {supersededAttached.length > 0 && ` · ${supersededAttached.length} superseded`}
                      {archivedAttached.length > 0 && ` · ${archivedAttached.length} archived`}
                    </span>
                    {party === 'RECYCLER' && ['RECYCLER_RECEIPT', 'PROCESSING_RECOVERY', 'RECYCLING_CERTIFICATE', 'OTHER_SUPPORTING'].includes(category) && <button type="button" disabled={!uploadable} onClick={event => { event.preventDefault(); event.stopPropagation(); const details = event.currentTarget.closest('details'); if (details) details.open = true; evidenceInputRefs.current[category]?.click(); }} className="inline-flex items-center gap-1 rounded-md bg-teal-700 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-slate-300" title={!uploadable ? uploadDisabledReason : `Choose ${card.title}`}><Upload className="h-3.5 w-3.5" aria-hidden="true" /> Upload</button>}
                  </div>
                </summary>

                <div className="mt-3 border-t border-slate-100 pt-3">
                {party !== 'RECYCLER' && <p className="mt-2 text-[10px] text-slate-500">Supports: {card.checks.join(' · ')}</p>}
                {!activeAttached.length && party !== 'RECYCLER' && <><p className="mt-2 text-xs text-slate-500">{emptyState}</p><p className="mt-1 text-[10px] text-slate-400">Verification: {due && required ? 'Not run; no file to check' : !due ? 'Waiting for the matching workflow stage' : 'Not applicable unless evidence is provided'}</p></>}

                {attached.map(item => {
                  const verification = STATUS_STYLE[item.verification_status || 'PENDING_HUMAN_REVIEW'];
                  const StatusIcon = verification.icon;
                  const evidenceStatus = EVIDENCE_STATUS_STYLE[item.status || 'ACTIVE'] || EVIDENCE_STATUS_STYLE.ACTIVE;
                  const isSuperseded = item.status === 'SUPERSEDED';
                  const isArchived = item.status === 'ARCHIVED';
                  const isPendingReview = item.status === 'PENDING_REVIEW';

                  return (
                    <div id={`evidence-${item.id}`} key={item.id} className={`mt-3 rounded-md p-3 ${isSuperseded || isArchived ? 'bg-slate-50/50 opacity-60' : isPendingReview ? 'bg-purple-50/30 border border-purple-200' : 'bg-slate-50'}`}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2">
                          <FileText className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
                          <div className="min-w-0">
                            <p className="truncate text-xs font-medium text-slate-800">
                              {item.filename}
                              {(item.version_number ?? 1) > 1 && <span className="ml-1 text-[10px] text-slate-500">v{item.version_number}</span>}
                            </p>
                            <p className="text-[10px] text-slate-500">
                              {item.uploaded_by?.name || item.source} · {item.uploaded_by?.organisation || item.source} · {formatDate(item.uploaded_at)}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${evidenceStatus.className}`}>
                            {evidenceStatus.label}
                          </span>
                          {!isSuperseded && !isArchived && (
                            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${verification.className}`}>
                              <StatusIcon className="h-3 w-3" aria-hidden="true" />{verification.label}
                            </span>
                          )}
                          <button type="button" onClick={() => void openEvidenceFile(claimId, item.id).catch(error => setMessages(current => ({ ...current, [category]: error.message })))} className="inline-flex items-center gap-1 text-xs font-medium text-teal-700 hover:text-teal-900">
                            Inspect <ExternalLink className="h-3 w-3" aria-hidden="true" />
                          </button>
                          <button type="button" onClick={() => handleDownload(item.id, item.filename)} className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-800">
                            <Download className="h-3 w-3" aria-hidden="true" />
                          </button>
                          <button type="button" onClick={() => void loadVersions(item.id)} className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-800" title="Version history">
                            <History className="h-3 w-3" aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                      {party !== 'RECYCLER' && <p className="mt-1 break-all text-[10px] text-slate-400">
                        {item.source} · {item.size_bytes.toLocaleString()} bytes · SHA-256 {item.sha256}
                        {item.linked_entity_type && ` · linked: ${item.linked_entity_type}/${item.linked_entity_id}`}
                      </p>}
                      {item.replacement_reason && (
                        <p className="mt-1 text-[10px] text-orange-600">
                          {isSuperseded ? 'Superseded' : isArchived ? 'Archived' : 'Replaced'}: {item.replacement_reason}
                        </p>
                      )}
                      {isPendingReview && (
                        <p className="mt-1 text-[10px] text-purple-600 font-medium">
                          ⏳ This replacement is awaiting government review before it can be accepted.
                        </p>
                      )}
                      {party === 'RECYCLER' ? <details className="mt-2 text-[10px] text-slate-500"><summary className="cursor-pointer">Check details</summary><p className="mt-1">Extraction: {item.extraction_status || 'PENDING'}{item.extraction_provenance?.method ? ` · ${item.extraction_provenance.method}` : ''}. Authenticity is not verified.</p>{item.verification_checks?.length > 0 && <ul className="mt-1 list-inside list-disc">{item.verification_checks.map((check, index) => <li key={`${item.id}-${index}`}>{check}</li>)}</ul>}<p className="mt-1 break-all">SHA-256 {item.sha256}{item.linked_entity_type && ` · linked: ${item.linked_entity_type}/${item.linked_entity_id}`}</p></details> : <><p className="mt-1 text-[10px] text-slate-600">Extraction: {item.extraction_status || 'PENDING'}{item.extraction_provenance?.method ? ` · ${item.extraction_provenance.method}` : ''}. Authenticity: not verified.</p>{item.verification_checks?.length > 0 && <ul className="mt-2 list-inside list-disc space-y-0.5 text-[10px] text-slate-600">{item.verification_checks.map((check, index) => <li key={`${item.id}-${index}`}>{check}</li>)}</ul>}</>}
                      {item.extracted_data && party !== 'RECYCLER' && <div className="mt-2 overflow-x-auto"><p className="mb-1 text-[10px] font-semibold text-slate-600">Document fields compared with claim entry · automatic consistency check only</p><table className="w-full text-left text-[10px]"><thead><tr className="text-slate-500"><th className="pr-3 font-medium">Field</th><th className="pr-3 font-medium">Extracted</th><th className="pr-3 font-medium">Entered in claim</th><th className="font-medium">Check</th></tr></thead><tbody>{Object.entries(item.extracted_data).filter(([key]) => key !== '_provenance').map(([key, value]) => { const source = item.extraction_provenance?.field_sources?.[key]; const details = item.extraction_provenance?.field_details?.[key] || {}; const compared = compareExtractedFields(item, claim)?.find(field => field.key === key); const statusStyle = compared?.result === 'MISMATCH' ? 'text-red-700 bg-red-50' : compared?.result === 'MATCH' ? 'text-emerald-700 bg-emerald-50' : 'text-slate-500 bg-slate-100'; const displayEntered = compared?.entered === null || compared?.entered === undefined || compared?.entered === '' ? 'Not entered / not applicable' : `${String(compared.entered)}${['quantity', 'net_weight_kg', 'received_quantity_kg', 'processing_input_kg', 'recovered_quantity_kg', 'residual_quantity_kg'].includes(key) ? ' kg' : ''}`; const displayExtracted = `${String(value)}${key === 'quantity' && item.extracted_data?.quantity_unit ? ` ${item.extracted_data.quantity_unit}` : ['net_weight_kg', 'received_quantity_kg', 'processing_input_kg', 'recovered_quantity_kg', 'residual_quantity_kg'].includes(key) ? ' kg' : ''}`; return <tr key={key} className="border-t border-slate-200"><td className="pr-3 py-1 capitalize">{key.replace(/_/g, ' ')}</td><td className="pr-3 py-1 break-words">{displayExtracted}<span className="block text-slate-400">{source || 'unknown'}{details.page ? ` · page ${details.page}` : ''}{typeof details.confidence === 'number' ? ` · ${Math.round(details.confidence * 100)}% extraction confidence` : ''}</span></td><td className="pr-3 py-1 break-words">{displayEntered}</td><td className="py-1"><span className={`rounded px-1.5 py-0.5 ${statusStyle}`}>{compared?.result === 'MATCH' ? 'Matches' : compared?.result === 'MISMATCH' ? 'Mismatch' : claim ? 'Not comparable' : 'Claim unavailable'}</span></td></tr>; })}</tbody></table><p className="mt-1 text-[9px] text-slate-500">Quantity tolerance is 5%; dates allow a one-day difference. A match does not verify document authenticity.</p></div>}

                      {/* Replace / Archive actions */}
                      {!isSuperseded && !isArchived && party !== 'AUDITOR' && (
                        <div className="mt-2 flex gap-2">
                          {canReplace(item) && (
                            <button type="button" onClick={() => setReplaceTarget(item.id)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-amber-700 bg-amber-50 hover:bg-amber-100 transition-colors">
                              <RefreshCw className="h-3 w-3" aria-hidden="true" /> Replace
                            </button>
                          )}
                          {canArchive(item) && (
                            <button type="button" onClick={() => setArchiveTarget(item.id)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-red-600 bg-red-50 hover:bg-red-100 transition-colors">
                              <Archive className="h-3 w-3" aria-hidden="true" /> Archive
                            </button>
                          )}
                        </div>
                      )}

                      {/* Replace dialog */}
                      {replaceTarget === item.id && (
                        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50/50 p-3 space-y-2">
                          <p className="text-xs font-medium text-amber-800">Replace "{item.filename}"{finalDecision ? ' · government review required' : ''}</p>
                          <input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={e => setReplaceFile(e.target.files?.[0] ?? null)} className="block w-full text-xs text-slate-600 file:mr-2 file:rounded-md file:border-0 file:bg-amber-100 file:px-2 file:py-1 file:text-[10px]" />
                          <textarea placeholder="Reason for replacement (required, min 3 chars)" value={replaceReason} onChange={e => setReplaceReason(e.target.value)} rows={2} className="w-full rounded border border-amber-200 px-2 py-1 text-xs text-slate-700 placeholder:text-slate-400" />
                          <div className="flex gap-2">
                            <Button size="sm" onClick={handleReplace} loading={replacing} disabled={!replaceFile || replaceReason.trim().length < 3}>
                              <RefreshCw className="h-3 w-3" /> Confirm Replace
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => { setReplaceTarget(null); setReplaceFile(null); setReplaceReason(''); }}>
                              <XCircle className="h-3 w-3" /> Cancel
                            </Button>
                          </div>
                        </div>
                      )}

                      {/* Archive dialog */}
                      {archiveTarget === item.id && (
                        <div className="mt-3 rounded-md border border-red-200 bg-red-50/50 p-3 space-y-2">
                          <p className="text-xs font-medium text-red-700">Archive "{item.filename}"</p>
                          <p className="text-[10px] text-red-600">The file will be preserved but marked as archived. It will not be erased.</p>
                          <textarea placeholder="Reason for archival (required, min 3 chars)" value={archiveReason} onChange={e => setArchiveReason(e.target.value)} rows={2} className="w-full rounded border border-red-200 px-2 py-1 text-xs text-slate-700 placeholder:text-slate-400" />
                          <div className="flex gap-2">
                            <Button size="sm" onClick={handleArchive} loading={archiving} disabled={archiveReason.trim().length < 3}>
                              <Archive className="h-3 w-3" /> Confirm Archive
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => { setArchiveTarget(null); setArchiveReason(''); }}>
                              <XCircle className="h-3 w-3" /> Cancel
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}

                {party !== 'AUDITOR' && !finalDecision && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                    <label className="space-y-1 text-xs font-semibold text-slate-700 sm:col-span-2">
                      {uploadable ? 'Add a document' : 'Add a document · unavailable'}
                      <input ref={element => { evidenceInputRefs.current[category] = element; }} disabled={!uploadable} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp" onChange={event => setSelected(current => ({ ...current, [category]: event.target.files?.[0] }))} className="block w-full rounded-md border border-slate-200 bg-white p-2 text-xs font-normal text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-teal-50 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-teal-800 disabled:opacity-50" />
                      <span className="block text-[10px] font-normal text-slate-500">{selected[category]?.name || 'PDF or image · up to 10 MB'}</span>
                    </label>
                    <details className="text-[10px] text-slate-500 sm:col-span-2">
                      <summary className="cursor-pointer select-none font-medium">Advanced options</summary>
                      <div className="mt-2 grid gap-2 sm:grid-cols-2">
                        <label className="space-y-1">Optional check data (JSON)
                          <input disabled={!uploadable} type="file" accept=".json,application/json" onChange={event => setStructuredFiles(current => ({ ...current, [category]: event.target.files?.[0] }))} className="block w-full text-xs text-slate-600 file:mr-2 file:rounded-md file:border-0 file:bg-slate-100 file:px-2 file:py-1.5 file:text-[10px] disabled:opacity-50" />
                          {structuredFiles[category] && <span className="block">{structuredFiles[category]?.name}</span>}
                        </label>
                        <label className="space-y-1">Linked record type
                          <select disabled={!uploadable} value={linkedTypes[category] || 'CLAIM'} onChange={event => setLinkedTypes(current => ({ ...current, [category]: event.target.value }))} className="block w-full rounded border border-slate-200 bg-white px-2 py-1.5 text-xs">
                            {['CLAIM', 'TRANSPORT_LEG', 'RECEIPT', 'PROCESSING_BATCH', 'RESIDUAL_WASTE'].map(type => <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>)}
                          </select>
                        </label>
                        {['TRANSPORT_LEG', 'PROCESSING_BATCH'].includes(linkedTypes[category] || 'CLAIM') && <label className="space-y-1">Linked record ID<input disabled={!uploadable} value={linkedIds[category] || ''} onChange={event => setLinkedIds(current => ({ ...current, [category]: event.target.value }))} placeholder="Operational record ID" className="block w-full rounded border border-slate-200 px-2 py-1.5 text-xs" /></label>}
                      </div>
                    </details>
                    <Button type="button" size="sm" onClick={() => void upload(category)} loading={uploading === category} disabled={!uploadable || !selected[category] || uploading !== null}>
                      <Upload className="h-3.5 w-3.5" aria-hidden="true" /> Upload
                    </Button>
                    {!uploadable && <p className="text-[10px] text-slate-500 sm:col-span-3">{uploadDisabledReason}</p>}
                  </div>
                )}
                {messages[category] && <p className="mt-2 text-xs text-slate-600" role="status">{messages[category]}</p>}
                </div>
              </details>
            );
          })}
        </div>

        {/* Version History Modal */}
        {versionHistory && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={() => setVersionHistory(null)}>
            <div className="mx-4 w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-slate-800">
                  <History className="inline h-4 w-4 mr-1 text-slate-500" />
                  Version History
                </h3>
                <button onClick={() => setVersionHistory(null)} className="text-slate-400 hover:text-slate-700">
                  <XCircle className="h-5 w-5" />
                </button>
              </div>
              <p className="text-[10px] text-slate-500 mb-3">
                Logical ID: {versionHistory.logical_id} · Category: {versionHistory.category}
              </p>
              {versionLoading && <p className="text-xs text-slate-500">Loading…</p>}
              <div className="max-h-80 overflow-y-auto space-y-2">
                {versionHistory.versions.map(v => {
                  const vStatus = EVIDENCE_STATUS_STYLE[v.status] || EVIDENCE_STATUS_STYLE.ACTIVE;
                  return (
                    <div key={v.evidence_id} className={`rounded-lg border p-3 ${v.status === 'ACTIVE' ? 'border-emerald-200 bg-emerald-50/30' : v.status === 'PENDING_REVIEW' ? 'border-purple-200 bg-purple-50/30' : 'border-slate-200 bg-slate-50/50'}`}>
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-800">v{v.version_number} · {v.filename}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${vStatus.className}`}>{vStatus.label}</span>
                      </div>
                      <p className="mt-1 text-[10px] text-slate-500">
                        {v.uploaded_by?.name || 'Unknown'} ({v.uploaded_by?.role}) · {formatDate(v.uploaded_at)} · {v.size_bytes.toLocaleString()} bytes
                      </p>
                      <p className="mt-0.5 text-[10px] text-slate-400 break-all">SHA-256: {v.sha256}</p>
                      {v.replacement_reason && (
                        <p className="mt-1 text-[10px] text-orange-600">Reason: {v.replacement_reason}</p>
                      )}
                      <div className="mt-1 flex gap-2">
                        <button type="button" onClick={() => void openEvidenceFile(claimId, v.evidence_id).catch(() => {})} className="text-[10px] text-teal-700 hover:text-teal-900 font-medium">View</button>
                        <button type="button" onClick={() => handleDownload(v.evidence_id, v.filename)} className="text-[10px] text-slate-600 hover:text-slate-800 font-medium">Download</button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
