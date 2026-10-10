/**
 * API client — all claim operations go through the FastAPI backend.
 *
 * Uses the Vite dev-server proxy: /api/* → http://localhost:8000/api/*
 */

import type { EvidenceFile, EvidenceVersionHistory, RecyclingClaim, ApiResponse } from '@/types';
import { getAccessToken, type AccountRole, type AuthUser, type Persona } from '@/lib/auth';

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: {
    id: string;
    username: string;
    display_name: string;
    organisation: string;
    persona: Persona;
    role: AccountRole;
    facility_ids: string[];
    department?: string;
  };
}

export interface GeocodingResult {
  latitude: number;
  longitude: number;
  label: string;
}

export async function loginWithPassword(username: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
}

export function toAuthUser(user: LoginResponse['user']): AuthUser {
  return {
    id: user.id,
    username: user.username,
    name: user.display_name,
    organisation: user.organisation,
    persona: user.persona,
    role: user.role,
    facility_ids: user.facility_ids,
    department: user.department,
  };
}

export interface ClaimSubmissionPayload {
  producer_name: string;
  producer_registration_number: string;
  recycler_name: string;
  recycler_registration_number: string;
  recycler_facility_id?: string;
  waste_category: string;
  waste_subcategories: string[];
  declared_weight_kg: number;
  collection_date: string;
  vehicle_registration: string;
  driver_name: string;
  origin_lat: number;
  origin_lng: number;
  origin_address: string;
  destination_lat: number;
  destination_lng: number;
  destination_address: string;
  departed_at: string;
  arrived_at: string;
  notes?: string;
}

export interface RecyclerAccount {
  id: string;
  organisation: string;
  display_name: string;
  registration_number: string;
}

export interface ReceiptPayload {
  received_weight_kg: number;
  received_at: string;
  recycler_notes?: string;
}

export interface ProcessingBatchPayload {
  batch_id?: string;
  processed_output_kg: number;
  recovered_materials: { material: string; quantity_kg: number; grade?: string; destination_facility?: string }[];
  residual_waste_kg: number;
  processing_date: string;
  notes?: string;
}

export type ProcessingPayload = {
  batches: ProcessingBatchPayload[];
  finalize?: boolean;
  corrects_previous?: boolean;
  recycler_notes?: string;
} | {
  // Legacy aggregate shape is still accepted by the backend.
  processed_output_kg: number;
  recovered_materials_total_kg: number;
  residual_waste_kg: number;
  processing_date: string;
  recycler_notes?: string;
};

// ── Shared fetch helper ─────────────────────────────────────────────────

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const token = getAccessToken();
  // Build headers independently so RequestInit spread order cannot accidentally
  // discard the session token when a caller supplies custom headers.
  const headers = new Headers(options?.headers);
  if (!isFormData && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (token && !url.endsWith('/auth/login') && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    const payload = await res.json().catch(() => null) as { detail?: unknown } | null;
    const detail = payload?.detail;
    if (res.status === 422 && Array.isArray(detail)) {
      const messages = detail.map((item: { loc?: unknown[]; type?: string; ctx?: { min_length?: number } }) => {
        const field = String(item.loc?.[Math.max((item.loc?.length ?? 1) - 1, 0)] ?? '');
        const fieldNames: Record<string, string> = {
          processing_batch_id: 'Select a processing batch.',
          corrected_quantity: 'Enter a corrected quantity of zero or more.',
          reason: 'Enter a reason with at least five characters.',
          category: 'Choose an adjustment category.',
          field: 'Choose which measurement to correct.',
        };
        if (fieldNames[field]) return fieldNames[field];
        if (item.type === 'missing') return 'Complete all required fields.';
        if (item.type === 'string_too_short') return 'Enter the missing information and try again.';
        return 'Check the entered information and try again.';
      });
      throw new Error([...new Set(messages)].join(' '));
    }
    if (typeof detail === 'string' && detail.trim()) throw new Error(detail);
    const fallbacks: Record<number, string> = {
      401: 'Your session has expired. Sign in again and retry.',
      403: 'You do not have permission to complete this action.',
      404: 'This record could not be found. Refresh the page and try again.',
      409: 'This record has changed or is not ready for this action. Refresh the page and try again.',
    };
    throw new Error(fallbacks[res.status] ?? 'We could not complete the request. Please try again.');
  }
  return res.json();
}

export async function openEvidenceFile(claimId: string, evidenceId: string): Promise<void> {
  const tab = window.open('about:blank', '_blank');
  if (!tab) throw new Error('Allow pop-ups to open evidence files');
  const token = getAccessToken();
  try {
    const response = await fetch(`/api/v1/claims/${claimId}/evidence/${evidenceId}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error(`Unable to load evidence (API ${response.status})`);
    const url = URL.createObjectURL(await response.blob());
    tab.location.href = url;
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    tab.close();
    throw error;
  }
}

// ── Public API (same signatures the pages already use) ──────────────────

export async function submitClaim(
  payload: ClaimSubmissionPayload
): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>('/api/v1/claims/', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchClaims(params?: {
  status?: string;
  page?: number;
  page_size?: number;
  sort_by?: 'submitted_at' | 'status' | 'reference_number';
  sort_order?: 'asc' | 'desc';
}): Promise<ApiResponse<RecyclingClaim[]>> {
  const pageSize = params?.page_size ?? 100;
  const getPage = (page: number) => {
    const query = new URLSearchParams();
    if (params?.status && params.status !== 'ALL') query.set('status', params.status);
    query.set('page', String(page));
    query.set('page_size', String(pageSize));
    if (params?.sort_by) query.set('sort_by', params.sort_by);
    if (params?.sort_order) query.set('sort_order', params.sort_order);
    return apiFetch<{items: RecyclingClaim[]; total: number; page: number; page_size: number; pages: number}>(`/api/v1/claims/?${query}`);
  };
  const first = await getPage(params?.page ?? 1);
  let data = first.items;
  // Existing dashboard and table callers expect the complete scoped result.
  // Explicit page requests remain available for incremental/paginated clients.
  if (params?.page === undefined) {
    for (let page = 2; page <= first.pages; page += 1) data = data.concat((await getPage(page)).items);
  }
  return {
    data,
    meta: { total: first.total, page: first.page, per_page: pageSize, pages: first.pages },
  };
}

export async function fetchClaim(id: string): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}`);
}

export async function dismissVerificationFlag(claimId: string, flagId: string, reason: string): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${claimId}/flags/${encodeURIComponent(flagId)}/dismiss`, {
    method: 'POST', body: JSON.stringify({ reason }),
  });
}

export async function fetchRecyclerAccounts(): Promise<RecyclerAccount[]> {
  return apiFetch<RecyclerAccount[]>('/api/v1/claims/recyclers');
}

export async function fetchAssignedClaims(): Promise<RecyclingClaim[]> {
  return apiFetch<RecyclingClaim[]>('/api/v1/claims/assigned');
}

export async function confirmClaimReceipt(id: string, payload: ReceiptPayload): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}/receipt`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function submitClaimProcessing(id: string, payload: ProcessingPayload): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}/processing`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function findLocations(query: string): Promise<GeocodingResult[]> {
  const response = await apiFetch<{ results: GeocodingResult[] }>(
    `/api/v1/claims/geocode?query=${encodeURIComponent(query)}`
  );
  return response.results;
}

export async function uploadClaimEvidence(
  id: string,
  file: File,
  category: EvidenceFile['category'] = 'OTHER_SUPPORTING',
  structuredDocumentData?: string,
  linkedEntityType?: string,
  linkedEntityId?: string
): Promise<RecyclingClaim> {
  const body = new FormData();
  body.append('file', file);
  body.append('category', category);
  if (structuredDocumentData) body.append('document_data', structuredDocumentData);
  if (linkedEntityType) body.append('linked_entity_type', linkedEntityType);
  if (linkedEntityId) body.append('linked_entity_id', linkedEntityId);
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}/evidence`, {
    method: 'POST',
    body,
  });
}

export async function replaceClaimEvidence(
  claimId: string,
  evidenceId: string,
  file: File,
  replacementReason: string,
  structuredDocumentData?: string
): Promise<RecyclingClaim> {
  const body = new FormData();
  body.append('file', file);
  body.append('replacement_reason', replacementReason);
  if (structuredDocumentData) body.append('document_data', structuredDocumentData);
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${claimId}/evidence/${evidenceId}/replace`, {
    method: 'POST',
    body,
  });
}

export async function fetchEvidenceVersions(
  claimId: string,
  evidenceId: string
): Promise<EvidenceVersionHistory> {
  return apiFetch<EvidenceVersionHistory>(`/api/v1/claims/${claimId}/evidence/${evidenceId}/versions`);
}

export async function archiveClaimEvidence(
  claimId: string,
  evidenceId: string,
  reason: string
): Promise<RecyclingClaim> {
  const body = new FormData();
  body.append('reason', reason);
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${claimId}/evidence/${evidenceId}/archive`, {
    method: 'POST',
    body,
  });
}

export async function downloadEvidenceFile(claimId: string, evidenceId: string): Promise<Blob> {
  const token = getAccessToken();
  const response = await fetch(`/api/v1/claims/${claimId}/evidence/${evidenceId}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new Error(`Unable to download evidence (API ${response.status})`);
  return response.blob();
}

export async function govApproveClaim(
  id: string,
  officialName: string
): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ official_name: officialName }),
  });
}

export async function govRejectClaim(
  id: string,
  officialName: string,
  reason: string
): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ official_name: officialName, reason }),
  });
}

export async function govRequestClaimClarification(id: string, reason: string): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}/clarification`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export async function govRecordAuditNote(
  id: string,
  auditType: 'ROUTINE' | 'INVESTIGATION',
  note: string
): Promise<RecyclingClaim> {
  return apiFetch<RecyclingClaim>(`/api/v1/claims/${id}/audit-note`, {
    method: 'POST',
    body: JSON.stringify({ audit_type: auditType, note }),
  });
}

export async function createMassBalanceAdjustment(id: string, payload: {
  processing_batch_id: string;
  field: 'PROCESSED_OUTPUT' | 'RESIDUAL_WASTE' | 'RECOVERED_MATERIAL';
  material_index?: number;
  corrected_quantity: number;
  category: string;
  reason: string;
  supporting_evidence_ids: string[];
}): Promise<unknown> {
  return apiFetch(`/api/v1/claims/${id}/adjustments`, { method: 'POST', body: JSON.stringify(payload) });
}

export async function reviewMassBalanceAdjustment(
  claimId: string, adjustmentId: string, approve: boolean, decision: string
): Promise<RecyclingClaim> {
  const result = await apiFetch<{ claim: RecyclingClaim }>(
    `/api/v1/claims/${claimId}/adjustments/${adjustmentId}/review?approve=${approve}`,
    { method: 'POST', body: JSON.stringify({ decision }) },
  );
  return result.claim;
}

export interface AdminFacility { id: string; name: string; registration_number: string; address: string;
  authorization_status: string; permitted_waste_categories: string[];
  memberships: { user_id: string; display_name: string; active: boolean; verified: boolean }[] }
export interface AdminAccount { id: string; username: string; display_name: string; organisation: string;
  role: AccountRole; is_active: boolean; facility_memberships: number; jurisdiction_assignments: number }
export interface AdminJurisdiction { id: string; name: string; boundary: number[][] | null;
  officers: { user_id: string; display_name: string }[] }
export interface AdminLegacy { claims: { id: string; reference_number: string; recycler_name: string;
  recycler_registration_number: string; original_facility_id: string | null; original_jurisdiction_id: string | null;
  unresolved: string[] }[]; recycler_accounts: { id: string; username: string; display_name: string; organisation: string }[];
  government_accounts: { id: string; username: string; display_name: string; organisation: string }[] }
export interface AdminActivity { id: string; sequence_no: number; actor_user_id: string; actor_display_name: string;
  actor_role: string; action_type: string; entity_type: string; entity_id: string; occurred_at: string;
  reason: string; previous_values: unknown; new_values: unknown; previous_hash: string; event_hash: string }

export const adminApi = {
  facilities: () => apiFetch<AdminFacility[]>('/api/v1/admin/facilities'),
  accounts: () => apiFetch<AdminAccount[]>('/api/v1/admin/accounts'),
  jurisdictions: () => apiFetch<AdminJurisdiction[]>('/api/v1/admin/jurisdictions'),
  legacy: () => apiFetch<AdminLegacy>('/api/v1/admin/legacy'),
  activity: () => apiFetch<AdminActivity[]>('/api/v1/admin/activity'),
  saveFacility: (body: unknown) => apiFetch('/api/v1/admin/facilities', { method: 'POST', body: JSON.stringify(body) }),
  setMembership: (facilityId: string, userId: string, body: unknown) => apiFetch(`/api/v1/admin/facilities/${facilityId}/members/${userId}`, { method: 'POST', body: JSON.stringify(body) }),
  revokeMembership: (facilityId: string, userId: string, reason: string) => apiFetch(`/api/v1/admin/facilities/${facilityId}/members/${userId}`, { method: 'DELETE', body: JSON.stringify({ reason }) }),
  saveJurisdiction: (id: string, body: unknown) => apiFetch(`/api/v1/admin/jurisdictions/${id}`, { method: 'POST', body: JSON.stringify(body) }),
  assignOfficer: (id: string, userId: string, reason: string) => apiFetch(`/api/v1/admin/jurisdictions/${id}/officers/${userId}`, { method: 'POST', body: JSON.stringify({ reason }) }),
  revokeOfficer: (id: string, userId: string, reason: string) => apiFetch(`/api/v1/admin/jurisdictions/${id}/officers/${userId}`, { method: 'DELETE', body: JSON.stringify({ reason }) }),
  setAccountActive: (id: string, active: boolean, reason: string) => apiFetch(`/api/v1/admin/accounts/${id}/status?active=${active}`, { method: 'POST', body: JSON.stringify({ reason }) }),
  resolveLegacy: (id: string, body: unknown) => apiFetch(`/api/v1/admin/legacy/claims/${id}/resolve`, { method: 'POST', body: JSON.stringify(body) }),
};
