export type ClaimStatus =
  | 'SUBMITTED'
  | 'AWAITING_RECYCLER_CONFIRMATION'
  | 'RECEIVED'
  | 'PENDING'
  | 'READY_FOR_VERIFICATION'
  | 'PROCESSING'
  | 'AWAITING_CLARIFICATION'
  | 'APPROVED'
  | 'VERIFIED'
  | 'FLAGGED'
  | 'REJECTED';

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type UserRole = 'PRODUCER' | 'RECYCLER' | 'AUDITOR' | 'REGULATOR';

export interface GpsCoordinate {
  lat: number;
  lng: number;
  timestamp: string;
  accuracy_m: number;
}

export interface EvidenceFile {
  id: string;
  logical_id?: string;
  type: 'CERTIFICATE' | 'INVOICE' | 'PHOTO' | 'MANIFEST' | 'WEIGHT_SLIP';
  filename: string;
  s3_key: string;
  sha256: string;
  size_bytes: number;
  uploaded_at: string;
  extraction_status: 'PENDING' | 'COMPLETED' | 'PARTIAL' | 'FAILED';
  extracted_data?: Record<string, string | number | Record<string, string>>;
  extraction_provenance?: { method: string; extractor_version?: string; page_count?: number; authenticity_status?: string; field_sources: Record<string, string>; field_details?: Record<string, Record<string, unknown>> } | null;
  source: 'PRODUCER' | 'RECYCLER' | 'TRANSPORTER' | 'SYSTEM';
  category: 'COLLECTION_WEIGHT_SLIP' | 'TRANSPORT_CHALLAN' | 'RECYCLER_RECEIPT' | 'PROCESSING_RECOVERY' | 'RECYCLING_CERTIFICATE' | 'OTHER_SUPPORTING';
  uploaded_by?: { id: string; name: string; organisation: string; role: string } | null;
  verification_status: 'PENDING' | 'METADATA_PROVIDED' | 'EXTRACTED_UNVERIFIED' | 'METADATA_CONSISTENT' | 'DISCREPANCY_DETECTED' | 'PENDING_HUMAN_REVIEW' | 'HUMAN_VERIFIED' | 'UNAVAILABLE';
  verification_checks: string[];
  // Versioning fields
  version_number?: number;
  status?: 'ACTIVE' | 'SUPERSEDED' | 'ARCHIVED' | 'PENDING_REVIEW';
  replaced_by_id?: string | null;
  replacement_reason?: string | null;
  linked_entity_type?: string | null;
  linked_entity_id?: string | null;
  mime_type?: string;
}

export interface EvidenceVersionInfo {
  evidence_id: string;
  version_number: number;
  filename: string;
  sha256: string;
  size_bytes: number;
  mime_type: string;
  uploaded_at: string;
  uploaded_by: { id: string; name: string; role: string } | null;
  status: string;
  replacement_reason: string | null;
  replaced_by_id: string | null;
  linked_entity_type: string | null;
  linked_entity_id: string | null;
}

export interface EvidenceVersionHistory {
  logical_id: string;
  category: string;
  versions: EvidenceVersionInfo[];
}

export interface TransportLeg {
  vehicle_registration: string;
  driver_name: string;
  origin: GpsCoordinate;
  destination: GpsCoordinate;
  declared_weight_kg: number;
  actual_weight_kg?: number;
  departed_at: string;
  arrived_at: string;
  distance_km: number;
}

export interface MassBalance {
  declared_input_kg: number;
  received_input_kg: number | null;
  processed_output_kg: number | null;
  recovered_materials: RecoveredMaterial[];
  residual_waste_kg: number | null;
  variance_pct: number;
  unexplained_difference_kg: number | null;
  unexplained_variance_pct: number | null;
  tolerance_pct: number;
}

export interface RecoveredMaterial {
  material: string;
  quantity_kg: number;
  grade: string;
  destination_facility: string;
}

export interface VerificationFlag {
  flag_id?: string;
  rule_version?: string;
  detected_at?: string;
  status?: 'ACTIVE' | 'RESOLVED' | 'DISMISSED';
  resolved_at?: string | null;
  resolution_reason?: string | null;
  resolution_type?: string | null;
  rule_name?: string;
  rule_category?: string;
  rationale?: string;
  recommended_action?: string;
  related_record_ids?: string[];
  code: string;
  layer:
    | 'DOCUMENT'
    | 'IMAGE'
    | 'GEOSPATIAL'
    | 'MASS_BALANCE'
    | 'DUPLICATE'
    | 'GRAPH'
    | 'ML';
  severity: 'INFO' | 'WARNING' | 'CRITICAL';
  description: string;
  evidence_ids: string[];
  rule_reference?: string;
  actual_values?: Record<string, number | null>;
  expected_relationship?: string;
  difference_kg?: number | null;
  variance_pct?: number | null;
  risk_contribution?: number;
  related_claim_ids?: string[];
  matched_fields?: string[];
}

export interface VerificationResult {
  claim_id: string;
  risk_score: number;
  risk_level: RiskLevel;
  flags: VerificationFlag[];
  processing_duration_ms: number;
  verified_at: string;
  model_version: string;
  explainability: ExplainabilityBreakdown;
}

export interface ExplainabilityBreakdown {
  document_score: number;
  image_score: number | null;
  geospatial_score: number;
  mass_balance_score: number;
  duplicate_score: number;
  graph_score: number | null;
  ml_anomaly_score: number | null;
  rule_contributions: RuleContribution[];
  score_history?: { calculated_at: string; score: number; risk_band: RiskLevel; ruleset_version: string; active_flag_ids: string[]; active_flags?: { flag_id: string; rule_id: string; code: string; contribution: number; description: string; actual_values: Record<string, number | null> }[] }[];
}

export interface RuleContribution {
  rule_id: string;
  label: string;
  score_delta: number;
  triggered: boolean;
  details: string;
}

export interface RecyclingClaim {
  id: string;
  reference_number: string;
  status: ClaimStatus;
  recycler_user_id?: string | null;
  recycler_facility_id?: string | null;
  jurisdiction_id?: string | null;
  producer: Organization;
  recycler: Organization;
  waste_category: string;
  waste_subcategories: string[];
  collection_date?: string;
  transport: TransportLeg[];
  mass_balance: MassBalance;
  evidence: EvidenceFile[];
  submitted_at: string;
  updated_at: string;
  received_at?: string | null;
  processing_date?: string | null;
  processing_completed_at?: string | null;
  recycler_notes?: string | null;
  clarification_reason?: string | null;
  processing_batches?: ProcessingBatchRecord[];
  audit_history?: ClaimAuditEvent[];
  audit_events?: AuditEventRecord[];
  audit_chain_valid?: boolean;
  effective_processing_batches?: ProcessingBatchRecord[];
  mass_balance_adjustments?: MassBalanceAdjustment[];
  original_mass_balance?: { processed_output_kg: number | null; recovered_materials: RecoveredMaterial[]; residual_waste_kg: number | null };
  verification_result?: VerificationResult;
  notes?: string;
}

export interface ProcessingBatchRecord {
  batch_id: string;
  processed_output_kg: number;
  recovered_materials: RecoveredMaterial[];
  residual_waste_kg: number;
  processing_date: string;
  notes?: string | null;
  submitted_at: string;
  submitted_by: { user_id: string; name: string; organisation: string; role: string };
}

export interface ClaimAuditEvent {
  action: string;
  occurred_at: string;
  actor: { user_id: string; name: string; organisation: string; role: string };
  [key: string]: unknown;
}

export interface AuditEventRecord {
  id: string;
  claim_id: string;
  sequence_no: number;
  entity_type: string;
  related_entity_id?: string | null;
  actor_user_id?: string | null;
  actor_role?: string | null;
  actor_display_name?: string | null;
  action_type: string;
  occurred_at?: string;
  previous_values?: Record<string, unknown> | null;
  new_values?: Record<string, unknown> | null;
  reason?: string | null;
  related_flag_id?: string | null;
  related_adjustment_id?: string | null;
  request_correlation_id?: string | null;
  legacy_event: boolean;
  legacy_payload?: Record<string, unknown> | null;
  previous_hash: string;
  event_hash: string;
}

export interface MassBalanceAdjustment {
  id: string;
  claim_id: string;
  processing_batch_id: string;
  field: string;
  original_quantity: number;
  corrected_quantity: number;
  unit: string;
  category: string;
  reason: string;
  supporting_evidence_ids: string[];
  created_by_user_id: string;
  created_by_name?: string | null;
  created_at: string;
  review_status: 'PENDING' | 'APPROVED' | 'REJECTED';
  reviewed_by_user_id?: string | null;
  reviewed_by_name?: string | null;
  review_decision?: string | null;
  reviewed_at?: string | null;
}

export interface Organization {
  id: string;
  name: string;
  registration_number: string;
  country: string;
  city: string;
  certification_id?: string;
  certification_expiry?: string;
  is_authorized: boolean;
}

export interface DashboardStats {
  total_claims: number;
  pending: number;
  verified: number;
  flagged: number;
  rejected: number;
  avg_risk_score: number;
  high_risk_count: number;
  total_waste_kg_verified: number;
  claims_this_month: number;
  risk_distribution: { level: RiskLevel; count: number }[];
  flags_by_layer: { layer: string; count: number }[];
  monthly_trend: { month: string; verified: number; flagged: number }[];
}

export interface ApiResponse<T> {
  data: T;
  meta?: {
    total: number;
    page: number;
    per_page: number;
    pages?: number;
  };
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, string[]>;
}
