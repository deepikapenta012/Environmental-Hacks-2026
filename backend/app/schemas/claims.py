"""
Pydantic schemas for the Claims API.

ClaimCreate: flat payload matching the frontend ClaimSubmissionPayload.
ClaimResponse: rich nested structure matching the frontend RecyclingClaim type.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enums ────────────────────────────────────────────────────────────────


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWAITING_RECYCLER_CONFIRMATION = "AWAITING_RECYCLER_CONFIRMATION"
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    READY_FOR_VERIFICATION = "READY_FOR_VERIFICATION"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ── Request bodies ───────────────────────────────────────────────────────


class RecoveredMaterialInput(BaseModel):
    material: str = Field(min_length=1, max_length=100)
    quantity_kg: float = Field(ge=0)
    grade: str = ""
    destination_facility: str = ""


class ClaimCreate(BaseModel):
    """Flat payload matching the frontend ClaimSubmissionPayload."""

    producer_name: str = Field(min_length=2, max_length=200)
    producer_registration_number: str = Field(min_length=3, max_length=50)
    recycler_name: str = Field(min_length=2, max_length=200)
    recycler_registration_number: str = Field(min_length=3, max_length=50)
    recycler_facility_id: Optional[str] = None
    # Deprecated compatibility input. It is resolved only through a verified membership.
    recycler_user_id: Optional[str] = None
    waste_category: str = Field(min_length=5, max_length=200)
    waste_subcategories: list[str] = Field(default_factory=list)
    declared_weight_kg: float = Field(gt=0)
    collection_date: str
    vehicle_registration: str = Field(min_length=2, max_length=20)
    driver_name: str = Field(min_length=2, max_length=100)
    origin_lat: float = Field(ge=-90.0, le=90.0)
    origin_lng: float = Field(ge=-180.0, le=180.0)
    origin_address: str = ""
    destination_lat: float = Field(ge=-90.0, le=90.0)
    destination_lng: float = Field(ge=-180.0, le=180.0)
    destination_address: str = ""
    departed_at: str
    arrived_at: str
    notes: Optional[str] = None

    @field_validator("collection_date")
    @classmethod
    def validate_collection_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("collection_date must be an ISO date (YYYY-MM-DD)") from exc
        if parsed.isoformat() != value:
            raise ValueError("collection_date must be an ISO date (YYYY-MM-DD)")
        return value


class ReceiptConfirmation(BaseModel):
    received_weight_kg: float = Field(gt=0)
    received_at: datetime
    recycler_notes: Optional[str] = None


class ProcessingBatchInput(BaseModel):
    batch_id: Optional[str] = Field(default=None, min_length=1, max_length=80)
    processed_output_kg: float = Field(gt=0)
    recovered_materials: list[RecoveredMaterialInput] = Field(default_factory=list)
    residual_waste_kg: float = Field(ge=0)
    processing_date: str = Field(min_length=8, max_length=20)
    notes: Optional[str] = None

    @field_validator("processing_date")
    @classmethod
    def validate_processing_date(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("processing_date must be an ISO date (YYYY-MM-DD)") from exc
        if parsed.isoformat() != value:
            raise ValueError("processing_date must be an ISO date (YYYY-MM-DD)")
        return value


class ProcessingSubmission(BaseModel):
    # Legacy aggregate fields remain accepted for existing API clients.
    processed_output_kg: Optional[float] = Field(default=None, gt=0)
    recovered_materials_total_kg: Optional[float] = Field(default=None, ge=0)
    residual_waste_kg: Optional[float] = Field(default=None, ge=0)
    processing_date: Optional[str] = Field(default=None, min_length=8, max_length=20)
    batches: Optional[list[ProcessingBatchInput]] = None
    recycler_notes: Optional[str] = None
    finalize: bool = True
    corrects_previous: bool = False

    @field_validator("processing_date")
    @classmethod
    def validate_legacy_processing_date(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("processing_date must be an ISO date (YYYY-MM-DD)") from exc
        if parsed.isoformat() != value:
            raise ValueError("processing_date must be an ISO date (YYYY-MM-DD)")
        return value

    @model_validator(mode="after")
    def validate_processing_payload(self):
        if self.batches is not None:
            if not self.batches:
                raise ValueError("At least one processing batch is required")
        elif (
            self.processed_output_kg is None
            or self.recovered_materials_total_kg is None
            or self.residual_waste_kg is None
            or self.processing_date is None
        ):
            raise ValueError("Submit processing batches or all legacy aggregate measurements")
        return self


class ApproveBody(BaseModel):
    official_name: str


class RejectBody(BaseModel):
    official_name: str
    reason: str = Field(min_length=1)


class RequestClarificationBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class AuditNoteBody(BaseModel):
    audit_type: Literal["ROUTINE", "INVESTIGATION"]
    note: str = Field(min_length=3, max_length=2000)


class MassBalanceAdjustmentCreate(BaseModel):
    processing_batch_id: str = Field(min_length=1, max_length=100)
    field: Literal["PROCESSED_OUTPUT", "RESIDUAL_WASTE", "RECOVERED_MATERIAL"]
    material_index: int | None = Field(default=None, ge=0)
    corrected_quantity: float = Field(ge=0, le=1_000_000_000)
    category: Literal["MEASUREMENT_CORRECTION", "DOCUMENTED_PROCESSING_LOSS", "DATA_ENTRY_CORRECTION"]
    reason: str = Field(min_length=5, max_length=2000)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class MassBalanceAdjustmentReview(BaseModel):
    decision: str = Field(min_length=3, max_length=2000)


class FlagDismissBody(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("A reason with at least five non-space characters is required")
        return value


# ── Response models (matching frontend RecyclingClaim type) ──────────────


class GpsCoordinateResponse(BaseModel):
    lat: float
    lng: float
    timestamp: str
    accuracy_m: float


class OrganizationResponse(BaseModel):
    id: str
    name: str
    registration_number: str
    country: str
    city: str
    is_authorized: bool


class TransportLegResponse(BaseModel):
    vehicle_registration: str
    driver_name: str
    origin: GpsCoordinateResponse
    destination: GpsCoordinateResponse
    declared_weight_kg: float
    actual_weight_kg: Optional[float] = None
    departed_at: str
    arrived_at: str
    distance_km: float


class MassBalanceResponse(BaseModel):
    declared_input_kg: float
    received_input_kg: Optional[float] = None
    processed_output_kg: Optional[float] = None
    recovered_materials: list = Field(default_factory=list)
    residual_waste_kg: Optional[float] = None
    variance_pct: float
    unexplained_difference_kg: Optional[float] = None
    unexplained_variance_pct: Optional[float] = None
    tolerance_pct: float


class EvidenceUploaderResponse(BaseModel):
    id: str
    name: str
    organisation: str
    role: str


class EvidenceResponse(BaseModel):
    id: str
    type: str
    filename: str
    s3_key: str
    sha256: str
    size_bytes: int
    uploaded_at: str
    extraction_status: str
    extracted_data: Optional[dict] = None
    source: str = "PRODUCER"
    category: str = "OTHER_SUPPORTING"
    uploaded_by: Optional[EvidenceUploaderResponse] = None
    verification_status: str = "PENDING"
    verification_checks: list[str] = Field(default_factory=list)


class VerificationFlagResponse(BaseModel):
    flag_id: Optional[str] = None
    rule_version: Optional[str] = None
    detected_at: Optional[str] = None
    status: str = "ACTIVE"
    resolved_at: Optional[str] = None
    resolution_reason: Optional[str] = None
    resolution_type: Optional[str] = None
    rule_name: Optional[str] = None
    rule_category: Optional[str] = None
    rationale: Optional[str] = None
    recommended_action: Optional[str] = None
    related_record_ids: list[str] = Field(default_factory=list)
    code: str
    layer: str
    severity: str
    description: str
    evidence_ids: list[str]
    rule_reference: Optional[str] = None
    actual_values: dict[str, float | None] = Field(default_factory=dict)
    expected_relationship: str = ""
    difference_kg: Optional[float] = None
    variance_pct: Optional[float] = None
    risk_contribution: int = 0
    related_claim_ids: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)


class RuleContributionResponse(BaseModel):
    rule_id: str
    label: str
    score_delta: int
    triggered: bool
    details: str


class ExplainabilityResponse(BaseModel):
    document_score: int
    image_score: Optional[int] = None
    geospatial_score: int
    mass_balance_score: int
    duplicate_score: int
    graph_score: Optional[int] = None
    ml_anomaly_score: Optional[int] = None
    rule_contributions: list[RuleContributionResponse]
    score_history: list[dict] = Field(default_factory=list)


class VerificationResultResponse(BaseModel):
    claim_id: str
    risk_score: int
    risk_level: RiskLevel
    flags: list[VerificationFlagResponse]
    processing_duration_ms: int
    verified_at: str
    model_version: str
    explainability: ExplainabilityResponse


class ClaimResponse(BaseModel):
    id: str
    reference_number: str
    status: ClaimStatus
    producer: OrganizationResponse
    recycler: OrganizationResponse
    waste_category: str
    waste_subcategories: list[str]
    transport: list[TransportLegResponse]
    mass_balance: MassBalanceResponse
    evidence: list[EvidenceResponse]
    submitted_at: str
    updated_at: str
    recycler_user_id: Optional[str] = None
    received_at: Optional[str] = None
    processing_date: Optional[str] = None
    processing_completed_at: Optional[str] = None
    recycler_notes: Optional[str] = None
    clarification_reason: Optional[str] = None
    processing_batches: list[dict] = Field(default_factory=list)
    audit_history: list[dict] = Field(default_factory=list)
    verification_result: Optional[VerificationResultResponse] = None
    notes: Optional[str] = None
