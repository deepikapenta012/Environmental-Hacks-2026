"""
ORM models for E-Waste ChainGuard.

Tables: users, claims, transport_legs, evidence, verification_results.
Complex nested data (flags, explainability, subcategories) stored as JSON
columns — appropriate for SQLite dev and PostgreSQL in production.
"""

from __future__ import annotations

import uuid
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Boolean,
    UniqueConstraint,
    CheckConstraint,
    event as sqlalchemy_event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── User ─────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    organisation: Mapped[str] = mapped_column(String(200), nullable=False)
    persona: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # USER | GOV_OFFICIAL
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="PRODUCER", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class RecyclerFacility(Base):
    __tablename__ = "recycler_facilities"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    authorization_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    permitted_waste_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class FacilityMembership(Base):
    __tablename__ = "facility_memberships"
    __table_args__ = (UniqueConstraint("user_id", "facility_id", name="uq_facility_member"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("recycler_facilities.id"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user: Mapped[User] = relationship()


class GovernmentJurisdiction(Base):
    __tablename__ = "government_jurisdictions"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    boundary: Mapped[list | None] = mapped_column(JSON, nullable=True)


class GovernmentJurisdictionAssignment(Base):
    __tablename__ = "government_jurisdiction_assignments"
    __table_args__ = (UniqueConstraint("user_id", "jurisdiction_id", name="uq_gov_jurisdiction"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    jurisdiction_id: Mapped[str] = mapped_column(ForeignKey("government_jurisdictions.id"), nullable=False, index=True)
    user: Mapped[User] = relationship()


class AdminAuditEvent(Base):
    """Append-only administrative activity not attached to an individual claim."""
    __tablename__ = "admin_audit_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(30), nullable=False)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    previous_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[User] = relationship()


# ── Claim ────────────────────────────────────────────────────────────────


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=True, index=True
    )
    reference_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="AWAITING_RECYCLER_CONFIRMATION"
    )
    recycler_user_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=True, index=True
    )
    recycler_facility_id: Mapped[str | None] = mapped_column(ForeignKey("recycler_facilities.id"), nullable=True, index=True)
    jurisdiction_id: Mapped[str | None] = mapped_column(ForeignKey("government_jurisdictions.id"), nullable=True, index=True)
    legacy_audit_migrated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Parties
    producer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    producer_registration_number: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    recycler_name: Mapped[str] = mapped_column(String(200), nullable=False)
    recycler_registration_number: Mapped[str] = mapped_column(
        String(50), nullable=False
    )

    # Waste
    waste_category: Mapped[str] = mapped_column(String(200), nullable=False)
    waste_subcategories: Mapped[list | None] = mapped_column(
        JSON, default=list
    )
    declared_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    received_weight_kg: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    processed_output_kg: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    mass_balance_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clarification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_date: Mapped[str] = mapped_column(String(20), nullable=False)

    origin_address: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )
    destination_address: Mapped[str] = mapped_column(
        String(500), nullable=False, default=""
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recycler_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    transport_legs: Mapped[list[TransportLeg]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    evidence_files: Mapped[list[Evidence]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    verification_result: Mapped[VerificationResult | None] = relationship(
        back_populates="claim", uselist=False, cascade="all, delete-orphan"
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="claim", order_by="AuditEvent.sequence_no")
    mass_balance_adjustments: Mapped[list[MassBalanceAdjustment]] = relationship(
        back_populates="claim", order_by="MassBalanceAdjustment.created_at"
    )


class ClaimReferenceCounter(Base):
    """Atomic per-year sequence used to allocate public claim references."""
    __tablename__ = "claim_reference_counters"
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AuditEvent(Base):
    """Append-only event record with a per-claim SHA-256 chain."""
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("claim_id", "sequence_no", name="uq_audit_claim_sequence"),
        UniqueConstraint("legacy_source_key", name="uq_audit_legacy_source"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="CLAIM")
    related_entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor_display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    previous_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_flag_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_adjustment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    legacy_event: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    legacy_source_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    legacy_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    claim: Mapped[Claim] = relationship(back_populates="audit_events")
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


class MassBalanceAdjustment(Base):
    __tablename__ = "mass_balance_adjustments"
    __table_args__ = (
        CheckConstraint("original_quantity >= 0", name="ck_adjust_original_nonnegative"),
        CheckConstraint("corrected_quantity >= 0", name="ck_adjust_corrected_nonnegative"),
        CheckConstraint("review_status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_adjust_review_status"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    processing_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    field_key: Mapped[str] = mapped_column(String(160), nullable=False)
    original_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    corrected_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="kg")
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claim: Mapped[Claim] = relationship(back_populates="mass_balance_adjustments")
    creator: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_user_id])


def _immutable_audit_event(_mapper, _connection, _target):
    raise ValueError("Audit events are append-only")


sqlalchemy_event.listen(AuditEvent, "before_update", _immutable_audit_event)
sqlalchemy_event.listen(AuditEvent, "before_delete", _immutable_audit_event)
sqlalchemy_event.listen(AdminAuditEvent, "before_update", _immutable_audit_event)
sqlalchemy_event.listen(AdminAuditEvent, "before_delete", _immutable_audit_event)


# ── Transport Leg ────────────────────────────────────────────────────────


class TransportLeg(Base):
    __tablename__ = "transport_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("claims.id"), nullable=False
    )

    vehicle_registration: Mapped[str] = mapped_column(String(20), nullable=False)
    driver_name: Mapped[str] = mapped_column(String(100), nullable=False)

    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lng: Mapped[float] = mapped_column(Float, nullable=False)
    origin_timestamp: Mapped[str] = mapped_column(String(50), nullable=False)
    origin_accuracy_m: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )

    destination_lat: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lng: Mapped[float] = mapped_column(Float, nullable=False)
    destination_timestamp: Mapped[str] = mapped_column(String(50), nullable=False)
    destination_accuracy_m: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )

    declared_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    departed_at: Mapped[str] = mapped_column(String(50), nullable=False)
    arrived_at: Mapped[str] = mapped_column(String(50), nullable=False)

    # Back-reference
    claim: Mapped[Claim] = relationship(back_populates="transport_legs")


# ── Evidence ─────────────────────────────────────────────────────────────


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("claims.id"), nullable=False
    )

    # Stable logical ID shared across all versions of this document.
    logical_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # CERTIFICATE | INVOICE | PHOTO | MANIFEST | WEIGHT_SLIP
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/octet-stream")
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extraction_provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    extraction_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )  # PENDING | COMPLETED | FAILED
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="PRODUCER")
    category: Mapped[str] = mapped_column(
        String(40), nullable=False, default="OTHER_SUPPORTING"
    )
    uploaded_by_user_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("users.id"), nullable=True, index=True
    )
    uploader_role: Mapped[str] = mapped_column(String(30), nullable=False, default="PRODUCER")
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )

    # Evidence lifecycle: ACTIVE | SUPERSEDED | ARCHIVED | PENDING_REVIEW
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE", index=True
    )

    # Version tracking
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    replaced_by_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    replacement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Link to specific entity (claim, transport leg, processing batch, etc.)
    linked_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    linked_entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    uploader: Mapped[User | None] = relationship(foreign_keys=[uploaded_by_user_id])

    # Back-reference
    claim: Mapped[Claim] = relationship(back_populates="evidence_files")

    # Version history
    versions: Mapped[list[EvidenceVersion]] = relationship(
        back_populates="evidence", order_by="EvidenceVersion.version_number"
    )


class EvidenceVersion(Base):
    """Immutable record of each uploaded file revision."""
    __tablename__ = "evidence_versions"
    __table_args__ = (
        UniqueConstraint("evidence_id", "version_number", name="uq_evidence_version"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    uploader_role: Mapped[str] = mapped_column(String(30), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    replacement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extraction_provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    evidence: Mapped[Evidence] = relationship(back_populates="versions")
    uploader: Mapped[User] = relationship(foreign_keys=[uploaded_by_user_id])


# ── Verification Result ──────────────────────────────────────────────────


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("claims.id"), unique=True, nullable=False
    )

    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # LOW | MEDIUM | HIGH | CRITICAL
    flags: Mapped[list | None] = mapped_column(JSON, default=list)
    processing_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    explainability: Mapped[dict | None] = mapped_column(JSON, default=dict)

    # Back-reference
    claim: Mapped[Claim] = relationship(back_populates="verification_result")
