import { clsx, type ClassValue } from 'clsx';
import type { ClaimAuditEvent, ClaimStatus, RiskLevel } from '@/types';

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(new Date(iso));
}

export function formatWeight(kg: number): string {
  if (kg >= 1000) {
    return `${(kg / 1000).toFixed(2)} t`;
  }
  return `${kg.toLocaleString('en-GB')} kg`;
}

export function formatNumber(n: number): string {
  return n.toLocaleString('en-GB');
}

export function auditEventDetails(event: ClaimAuditEvent): string {
  const values = typeof event.values === 'object' && event.values !== null
    ? event.values as Record<string, unknown>
    : {};
  const previous = typeof event.previous === 'object' && event.previous !== null
    ? event.previous as Record<string, unknown>
    : {};
  if (typeof event.note === 'string') return event.note;
  if (typeof event.reason === 'string') return event.reason;
  if (event.action.startsWith('RECEIPT_')) {
    const oldWeight = previous.received_weight_kg;
    const newWeight = values.received_weight_kg;
    return `${oldWeight ?? '—'} kg → ${newWeight ?? '—'} kg received`;
  }
  if (typeof values.processed_output_kg === 'number') {
    return `Batch ${String(values.batch_id ?? '')}: ${values.processed_output_kg} kg processed, ${values.residual_waste_kg ?? 0} kg residual`;
  }
  if (Array.isArray(event.replaced_batches)) {
    const ids = event.replaced_batches.map(batch =>
      typeof batch === 'object' && batch !== null && 'batch_id' in batch ? String(batch.batch_id) : 'batch'
    );
    return `Replaced processing batches: ${ids.join(', ') || 'none'}`;
  }
  if (typeof event.category === 'string') {
    return `Evidence ${String(event.evidence_id ?? '')} · ${event.category} · SHA-256 ${String(event.sha256 ?? '')}`;
  }
  if (typeof event.declared_weight_kg === 'number') return `Declared weight: ${event.declared_weight_kg} kg`;
  if (typeof event.official_name === 'string') return `Decision recorded for ${event.official_name}`;
  return 'Recorded in the claim history.';
}

export function riskLevelConfig(level: RiskLevel) {
  const configs = {
    LOW: {
      label: 'Low Risk',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
      border: 'border-emerald-200',
      dot: 'bg-emerald-500',
      bar: '#10B981',
    },
    MEDIUM: {
      label: 'Moderate Risk',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      border: 'border-amber-200',
      dot: 'bg-amber-500',
      bar: '#F59E0B',
    },
    HIGH: {
      label: 'High Risk',
      bg: 'bg-orange-50',
      text: 'text-orange-700',
      border: 'border-orange-200',
      dot: 'bg-orange-500',
      bar: '#F97316',
    },
    CRITICAL: {
      label: 'Critical',
      bg: 'bg-red-50',
      text: 'text-red-700',
      border: 'border-red-200',
      dot: 'bg-red-500',
      bar: '#EF4444',
    },
  } as const;
  return configs[level];
}

export function claimStatusConfig(status: ClaimStatus) {
  const configs = {
    SUBMITTED: {
      label: 'Submitted',
      bg: 'bg-slate-100',
      text: 'text-slate-600',
    },
    AWAITING_RECYCLER_CONFIRMATION: {
      label: 'Awaiting Recycler',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
    },
    RECEIVED: {
      label: 'Received',
      bg: 'bg-blue-50',
      text: 'text-blue-700',
    },
    READY_FOR_VERIFICATION: {
      label: 'Ready for Verification',
      bg: 'bg-indigo-50',
      text: 'text-indigo-700',
    },
    PENDING: {
      label: 'Awaiting Government Review',
      bg: 'bg-slate-100',
      text: 'text-slate-600',
    },
    PROCESSING: {
      label: 'Processing',
      bg: 'bg-blue-50',
      text: 'text-blue-700',
    },
    AWAITING_CLARIFICATION: {
      label: 'Awaiting Clarification',
      bg: 'bg-amber-50',
      text: 'text-amber-700',
    },
    VERIFIED: {
      label: 'Verified',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
    },
    APPROVED: {
      label: 'Approved',
      bg: 'bg-emerald-50',
      text: 'text-emerald-700',
    },
    FLAGGED: {
      label: 'Flagged',
      bg: 'bg-orange-50',
      text: 'text-orange-700',
    },
    REJECTED: {
      label: 'Rejected',
      bg: 'bg-red-50',
      text: 'text-red-700',
    },
  } as const;
  return configs[status];
}

export function severityConfig(severity: 'INFO' | 'WARNING' | 'CRITICAL') {
  const configs = {
    INFO: {
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      border: 'border-l-blue-400',
      icon: 'text-blue-500',
    },
    WARNING: {
      bg: 'bg-amber-50',
      text: 'text-amber-800',
      border: 'border-l-amber-400',
      icon: 'text-amber-500',
    },
    CRITICAL: {
      bg: 'bg-red-50',
      text: 'text-red-800',
      border: 'border-l-red-500',
      icon: 'text-red-500',
    },
  } as const;
  return configs[severity];
}
