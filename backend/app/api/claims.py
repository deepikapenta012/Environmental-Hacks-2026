"""
Claims API — backed by SQLAlchemy + the deterministic verification engine.

Endpoints:
  POST   /claims/              Create claim (verification runs automatically)
  GET    /claims/              List claims (optional ?status= filter)
  GET    /claims/{id}          Get single claim
  POST   /claims/{id}/approve  Gov official approves
  POST   /claims/{id}/reject   Gov official rejects
  POST   /claims/{id}/verify   Re-run verification
"""

from __future__ import annotations

import time
import uuid
import hashlib
import hmac
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.config import get_settings
from app.auth import (GOVERNMENT_OFFICER, PRODUCER, RECYCLER_EMPLOYEE,
                      get_current_user, require_government_official, require_producer)
from app.models import (AuditEvent, Claim, ClaimReferenceCounter, Evidence, FacilityMembership, MassBalanceAdjustment, RecyclerFacility,
                        GovernmentJurisdiction, GovernmentJurisdictionAssignment, TransportLeg, User,
                        VerificationResult as VRModel)
from app.services.audit import (calculate_event_hash, event_hash_fields, request_correlation_id,
                                verify_event_chain, verify_event_chain_diagnostics)
from app.services.document_extraction import get_document_extractor
from app.services.geocoding import find_locations
from app.schemas import (
    AuditNoteBody,
    ApproveBody,
    ClaimCreate,
    FlagDismissBody,
    ProcessingSubmission,
    RequestClarificationBody,
    MassBalanceAdjustmentCreate,
    MassBalanceAdjustmentReview,
    ReceiptConfirmation,
    RejectBody,
)
from app.verification import (
    check_duplicate_evidence,
    check_duplicate_claims,
    check_document_consistency,
    check_evidence_ownership,
    check_evidence_replacements,
    check_stage_evidence,
    check_mass_balance,
    check_transport_speed,
    score_flags,
    haversine_km,
)
from app.verification.catalog import (DEFAULT_RULE_WEIGHTS, RULE_CATALOG, RULESET_VERSION,
                                     SCORING_NOTES, get_rule_definition)

router = APIRouter(prefix="/claims", tags=["Claims"])

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads"
MAX_STRUCTURED_DATA_SIZE = 16 * 1024
ALLOWED_EVIDENCE = {
    ".pdf": ("application/pdf", b"%PDF-", "CERTIFICATE"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff", "PHOTO"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff", "PHOTO"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n", "PHOTO"),
    ".webp": ("image/webp", b"RIFF", "PHOTO"),
}
EVIDENCE_CATEGORIES = {
    "COLLECTION_WEIGHT_SLIP": "PRODUCER",
    "TRANSPORT_CHALLAN": "PRODUCER",
    "RECYCLER_RECEIPT": "RECYCLER",
    "PROCESSING_RECOVERY": "RECYCLER",
    "RECYCLING_CERTIFICATE": "RECYCLER",
    "OTHER_SUPPORTING": "EITHER",
}
EVIDENCE_CATEGORY_CHECKS = {
    "COLLECTION_WEIGHT_SLIP": ["Document quantity consistency", "Declared-to-received mass reconciliation"],
    "TRANSPORT_CHALLAN": ["Transport route and timeline checks", "Party consistency"],
    "RECYCLER_RECEIPT": ["Declared-to-received mass reconciliation", "Recycler receipt document consistency"],
    "PROCESSING_RECOVERY": ["Processed-output mass balance", "Recovered plus residual reconciliation"],
    "RECYCLING_CERTIFICATE": ["Certificate identifier and entity consistency", "Duplicate evidence checks"],
    "OTHER_SUPPORTING": ["Document consistency when structured data is supplied", "Exact duplicate file check"],
}
EVIDENCE_MISMATCH_RULES = {
    "DUPLICATE_SHA256", "DUPLICATE_CLAIM", "DOC_ENTITY_MISMATCH",
    "DOC_QUANTITY_MISMATCH", "DOC_DATE_MISMATCH", "DOC_MATERIAL_MISMATCH",
    "DOC_CERTIFICATE_INVOICE_MISMATCH", "DOC_EVIDENCE_CONFLICT",
}
CHECKED_DOCUMENT_FIELDS = {
    "producer", "recycler", "quantity", "date", "material_type",
    "certificate_id", "invoice_id",
}


# ── Helpers ──────────────────────────────────────────────────────────────


def _iso(dt: datetime | None) -> str:
    """Datetime → ISO string. Appends Z for naive datetimes (SQLite strips tz)."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


def _load_claim(claim_id: str, db: Session, current_user: User) -> Claim:
    """Load a claim with all relationships, or raise 404."""
    claim = (
        db.query(Claim)
        .options(
            joinedload(Claim.transport_legs),
            joinedload(Claim.evidence_files),
            joinedload(Claim.verification_result),
            selectinload(Claim.audit_events),
            selectinload(Claim.mass_balance_adjustments),
        )
        .execution_options(populate_existing=True)
        .filter(Claim.id == claim_id)
        .filter(_scope_filter(db, current_user))
        .first()
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return claim


def _scope_filter(db: Session, user: User):
    if user.role == PRODUCER:
        return Claim.owner_user_id == user.id
    if user.role == RECYCLER_EMPLOYEE:
        facilities = db.query(FacilityMembership.facility_id).join(
            RecyclerFacility, RecyclerFacility.id == FacilityMembership.facility_id
        ).filter(FacilityMembership.user_id == user.id, FacilityMembership.active.is_(True),
                 FacilityMembership.verified.is_(True), RecyclerFacility.authorization_status == "AUTHORIZED")
        return Claim.recycler_facility_id.in_(facilities)
    if user.role == GOVERNMENT_OFFICER:
        jurisdictions = db.query(GovernmentJurisdictionAssignment.jurisdiction_id).filter(
            GovernmentJurisdictionAssignment.user_id == user.id)
        return Claim.jurisdiction_id.in_(jurisdictions)
    return Claim.id == "__no_access__"


def _assert_assigned_recycler(claim: Claim, current_user: User, db: Session) -> None:
    membership = db.query(FacilityMembership).join(
        RecyclerFacility, RecyclerFacility.id == FacilityMembership.facility_id
    ).filter(FacilityMembership.user_id == current_user.id,
             FacilityMembership.facility_id == claim.recycler_facility_id,
             FacilityMembership.active.is_(True), FacilityMembership.verified.is_(True),
             RecyclerFacility.authorization_status == "AUTHORIZED").first()
    if current_user.role != RECYCLER_EMPLOYEE or not membership:
        raise HTTPException(status_code=403, detail="Only the recycler assigned to this claim may confirm or process it")


def _point_in_boundary(longitude: float, latitude: float, boundary: list) -> bool:
    """Ray casting against configured GeoJSON-style [longitude, latitude] ring."""
    inside = False
    previous = len(boundary) - 1
    for index, point in enumerate(boundary):
        x1, y1 = point
        x2, y2 = boundary[previous]
        if ((y1 > latitude) != (y2 > latitude)) and longitude < (x2 - x1) * (latitude - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = index
    return inside


def _allocate_claim_reference(db: Session, year: int) -> str:
    """Allocate a per-year reference atomically inside the claim transaction."""
    value = db.execute(
        update(ClaimReferenceCounter)
        .where(ClaimReferenceCounter.year == year)
        .values(value=ClaimReferenceCounter.value + 1)
        .returning(ClaimReferenceCounter.value)
    ).scalar_one_or_none()
    if value is None:
        try:
            with db.begin_nested():
                db.add(ClaimReferenceCounter(year=year, value=8600))
                db.flush()
            value = 8600
        except IntegrityError:
            value = db.execute(
                update(ClaimReferenceCounter)
                .where(ClaimReferenceCounter.year == year)
                .values(value=ClaimReferenceCounter.value + 1)
                .returning(ClaimReferenceCounter.value)
            ).scalar_one()
    return f"EWC-{year}-{value:05d}"


def _audit_actor(user: User, role: str | None = None) -> dict:
    return {"user_id": user.id, "name": user.display_name, "organisation": user.organisation,
            "role": role or user.role}


def _append_audit(
    claim: Claim,
    action: str,
    user: User | None,
    db: Session,
    *,
    role: str | None = None,
    **details,
) -> None:
    values = dict(claim.mass_balance_details or {})
    history = list(values.get("audit_history") or [])
    occurred_at = datetime.now(timezone.utc).replace(tzinfo=None)
    history.append({"action": action, "occurred_at": _iso(occurred_at),
                    "actor": _audit_actor(user, role) if user else None, **details})
    values["audit_history"] = history
    claim.mass_balance_details = values
    # Serialize writers for this claim on databases that support row locking.
    db.query(Claim.id).filter(Claim.id == claim.id).with_for_update().first()
    previous = db.query(AuditEvent).filter_by(claim_id=claim.id).order_by(AuditEvent.sequence_no.desc()).first()
    structured_new = details.get("values") if isinstance(details.get("values"), dict) else {
        key: value for key, value in details.items() if key not in {"previous", "reason", "note"}
    }
    event = AuditEvent(
        id=f"evt_{uuid.uuid4().hex}", claim_id=claim.id,
        sequence_no=(previous.sequence_no + 1) if previous else 1,
        entity_type="CLAIM", related_entity_id=(details.get("evidence_id") or details.get("batch_id")),
        actor_user_id=user.id if user else None, actor_role=user.role if user else None,
        actor_display_name=user.display_name if user else None,
        action_type=action, occurred_at=occurred_at,
        previous_values=details.get("previous") if isinstance(details.get("previous"), dict) else None,
        new_values=structured_new,
        reason=details.get("reason") or details.get("note"),
        related_adjustment_id=details.get("adjustment_id"),
        request_correlation_id=request_correlation_id.get(),
        legacy_event=False, previous_hash=previous.event_hash if previous else "", event_hash="",
    )
    event.event_hash = calculate_event_hash(event_hash_fields(event))
    db.add(event)
    db.flush()


def _effective_processing(claim: Claim) -> tuple[list[dict], float, list[dict], float | None]:
    """Apply approved corrections in memory while leaving submitted batch records intact."""
    original = [dict(batch) for batch in ((claim.mass_balance_details or {}).get("processing_batches") or [])]
    effective = [dict(batch, recovered_materials=[dict(item) for item in batch.get("recovered_materials", [])])
                 for batch in original]
    approved = sorted((item for item in claim.mass_balance_adjustments if item.review_status == "APPROVED"),
                      key=lambda item: (item.reviewed_at or item.created_at, item.created_at, item.id))
    for adjustment in approved:
        batch = next((row for row in effective if row.get("batch_id") == adjustment.processing_batch_id), None)
        if batch is None:
            continue
        if adjustment.field_key == "processed_output_kg":
            batch["processed_output_kg"] = adjustment.corrected_quantity
        elif adjustment.field_key == "residual_waste_kg":
            batch["residual_waste_kg"] = adjustment.corrected_quantity
        elif adjustment.field_key.startswith("recovered_materials:"):
            index = int(adjustment.field_key.split(":", 1)[1])
            if 0 <= index < len(batch.get("recovered_materials", [])):
                batch["recovered_materials"][index]["quantity_kg"] = adjustment.corrected_quantity
    recovered: dict[tuple[str, str, str], dict] = {}
    for batch in effective:
        for material in batch.get("recovered_materials", []):
            key = (str(material.get("material", "Recovered materials")), str(material.get("grade", "")),
                   str(material.get("destination_facility", "")))
            entry = recovered.setdefault(key, {"material": key[0], "grade": key[1],
                "destination_facility": key[2], "quantity_kg": 0.0})
            entry["quantity_kg"] += float(material.get("quantity_kg", 0) or 0)
    output_total = sum(float(batch.get("processed_output_kg", 0) or 0) for batch in effective)
    residual_total = sum(float(batch.get("residual_waste_kg", 0) or 0) for batch in effective) if effective else None
    return effective, output_total, list(recovered.values()), residual_total


def _event_response(event: AuditEvent) -> dict:
    return {
        "id": event.id, "claim_id": event.claim_id, "sequence_no": event.sequence_no,
        "entity_type": event.entity_type, "related_entity_id": event.related_entity_id,
        "actor_user_id": event.actor_user_id, "actor_role": event.actor_role,
        "actor_display_name": event.actor_display_name, "action_type": event.action_type,
        "occurred_at": _iso(event.occurred_at), "previous_values": event.previous_values,
        "new_values": event.new_values, "reason": event.reason,
        "related_flag_id": event.related_flag_id, "related_adjustment_id": event.related_adjustment_id,
        "request_correlation_id": event.request_correlation_id,
        "legacy_event": event.legacy_event, "legacy_payload": event.legacy_payload,
        "previous_hash": event.previous_hash, "event_hash": event.event_hash,
    }


def _adjustment_response(item: MassBalanceAdjustment) -> dict:
    return {
        "id": item.id, "claim_id": item.claim_id, "processing_batch_id": item.processing_batch_id,
        "field": item.field_key, "original_quantity": item.original_quantity,
        "corrected_quantity": item.corrected_quantity, "unit": item.unit,
        "category": item.category, "reason": item.reason,
        "supporting_evidence_ids": item.supporting_evidence_ids or [],
        "created_by_user_id": item.created_by_user_id,
        "created_by_name": item.creator.display_name if item.creator else None,
        "created_at": _iso(item.created_at), "review_status": item.review_status,
        "reviewed_by_user_id": item.reviewed_by_user_id,
        "reviewed_by_name": item.reviewer.display_name if item.reviewer else None,
        "review_decision": item.review_decision, "reviewed_at": _iso(item.reviewed_at),
    }


def _build_response(claim: Claim) -> dict:
    """Convert ORM Claim → dict matching the frontend RecyclingClaim type."""

    # Transport legs
    transport = []
    for leg in claim.transport_legs:
        transport.append({
            "vehicle_registration": leg.vehicle_registration,
            "driver_name": leg.driver_name,
            "origin": {
                "lat": leg.origin_lat,
                "lng": leg.origin_lng,
                "timestamp": leg.origin_timestamp,
                "accuracy_m": leg.origin_accuracy_m,
            },
            "destination": {
                "lat": leg.destination_lat,
                "lng": leg.destination_lng,
                "timestamp": leg.destination_timestamp,
                "accuracy_m": leg.destination_accuracy_m,
            },
            "declared_weight_kg": leg.declared_weight_kg,
            "actual_weight_kg": claim.received_weight_kg if claim.received_at else None,
            "departed_at": leg.departed_at,
            "arrived_at": leg.arrived_at,
            "distance_km": round(haversine_km(leg.origin_lat, leg.origin_lng,
                                               leg.destination_lat, leg.destination_lng), 2),
        })

    # Mass balance
    details = claim.mass_balance_details or {}
    recovered_materials = details.get("recovered_materials") or []
    residual_waste_kg = details.get("residual_waste_kg")
    effective_batches, effective_output, effective_recovered, effective_residual = _effective_processing(claim)
    if effective_batches:
        recovered_materials = effective_recovered
        residual_waste_kg = effective_residual
    received_weight_kg = claim.received_weight_kg if claim.received_at else None
    processed_output_kg = (effective_output if effective_batches else claim.processed_output_kg) if claim.processing_completed_at else None
    if not claim.processing_completed_at:
        recovered_materials = []
        residual_waste_kg = None
    variance_pct = 0.0
    if claim.declared_weight_kg > 0 and received_weight_kg is not None:
        variance_pct = round(
            ((received_weight_kg - claim.declared_weight_kg)
             / claim.declared_weight_kg) * 100,
            1,
        )
    unexplained_difference_kg = None
    unexplained_variance_pct = None
    if processed_output_kg and processed_output_kg > 0 and residual_waste_kg is not None and recovered_materials:
        recovered_total = sum(float(item.get("quantity_kg", 0) or 0) for item in recovered_materials)
        unexplained_difference_kg = round(
            processed_output_kg - recovered_total - float(residual_waste_kg), 3
        )
        unexplained_variance_pct = round(
            abs(unexplained_difference_kg) / processed_output_kg * 100, 3
        )

    # Verification result
    vr_dict = None
    if claim.verification_result:
        vr = claim.verification_result
        vr_dict = {
            "claim_id": vr.claim_id,
            "risk_score": vr.risk_score,
            "risk_level": vr.risk_level,
            "flags": vr.flags or [],
            "processing_duration_ms": vr.processing_duration_ms,
            "verified_at": _iso(vr.verified_at),
            "model_version": vr.model_version,
            "explainability": vr.explainability or {},
        }

    # Evidence
    evidence = []
    for ev in claim.evidence_files:
        verification_checks = list(EVIDENCE_CATEGORY_CHECKS.get(ev.category, []))
        if vr_dict:
            verification_checks.extend(
                f"{flag.get('rule_reference') or flag.get('code')}: {flag.get('description')}"
                for flag in vr_dict["flags"]
                if ev.id in flag.get("evidence_ids", [])
            )
        evidence.append({
            "id": ev.id,
            "logical_id": getattr(ev, "logical_id", ev.id),
            "type": ev.type,
            "filename": ev.filename,
            "s3_key": ev.file_path,
            "sha256": ev.sha256,
            "size_bytes": ev.size_bytes,
            "uploaded_at": _iso(ev.uploaded_at),
            "extraction_status": ev.extraction_status,
            "extracted_data": ev.extracted_data,
            "extraction_provenance": getattr(ev, "extraction_provenance", None),
            "source": ev.source,
            "category": ev.category,
            "uploaded_by": ({
                "id": ev.uploader.id,
                "name": ev.uploader.display_name,
                "organisation": ev.uploader.organisation,
            "role": ev.uploader_role,
            } if ev.uploader else None),
            "verification_status": ev.verification_status,
            "verification_checks": verification_checks,
            "version_number": getattr(ev, "version_number", 1),
            "status": getattr(ev, "status", "ACTIVE"),
            "replaced_by_id": getattr(ev, "replaced_by_id", None),
            "replacement_reason": getattr(ev, "replacement_reason", None),
            "linked_entity_type": getattr(ev, "linked_entity_type", None),
            "linked_entity_id": getattr(ev, "linked_entity_id", None),
            "mime_type": getattr(ev, "mime_type", "application/octet-stream"),
        })

    return {
        "id": claim.id,
        "reference_number": claim.reference_number,
        "status": claim.status,
        "recycler_user_id": claim.recycler_user_id,
        "recycler_facility_id": claim.recycler_facility_id,
        "jurisdiction_id": claim.jurisdiction_id,
        "received_at": _iso(claim.received_at) if claim.received_at else None,
        "processing_date": claim.processing_date,
        "processing_completed_at": _iso(claim.processing_completed_at) if claim.processing_completed_at else None,
        "recycler_notes": claim.recycler_notes,
        "clarification_reason": claim.clarification_reason,
        "processing_batches": details.get("processing_batches", []),
        "audit_history": details.get("audit_history", []),
        "audit_events": [_event_response(event) for event in claim.audit_events],
        "audit_chain_valid": verify_event_chain(claim.audit_events),
        "effective_processing_batches": effective_batches,
        "mass_balance_adjustments": [_adjustment_response(item) for item in claim.mass_balance_adjustments],
        "producer": {
            "id": f"org_{claim.producer_registration_number[:8].lower()}",
            "name": claim.producer_name,
            "registration_number": claim.producer_registration_number,
            "country": "",
            "city": claim.origin_address,
            "is_authorized": True,
        },
        "recycler": {
            "id": f"org_{claim.recycler_registration_number[:8].lower()}",
            "name": claim.recycler_name,
            "registration_number": claim.recycler_registration_number,
            "country": "",
            "city": claim.destination_address,
            "is_authorized": True,
        },
        "waste_category": claim.waste_category,
        "waste_subcategories": claim.waste_subcategories or [],
        "collection_date": claim.collection_date,
        "transport": transport,
        "mass_balance": {
            "declared_input_kg": claim.declared_weight_kg,
            "received_input_kg": received_weight_kg,
            "processed_output_kg": processed_output_kg,
            "recovered_materials": recovered_materials,
            "residual_waste_kg": residual_waste_kg,
            "variance_pct": variance_pct,
            "unexplained_difference_kg": unexplained_difference_kg,
            "unexplained_variance_pct": unexplained_variance_pct,
            "tolerance_pct": get_settings().mass_balance_tolerance_pct,
        },
        "original_mass_balance": {
            "processed_output_kg": claim.processed_output_kg if claim.processing_completed_at else None,
            "recovered_materials": details.get("recovered_materials") or [],
            "residual_waste_kg": details.get("residual_waste_kg"),
        },
        "evidence": evidence,
        "submitted_at": _iso(claim.submitted_at),
        "updated_at": _iso(claim.updated_at),
        "verification_result": vr_dict,
        "notes": claim.notes,
    }


def _run_verification(claim: Claim, db: Session, actor: User | None = None) -> None:
    """Run deterministic verification rules and store/update the result."""
    if claim.received_at is None or claim.processing_completed_at is None:
        return
    start = time.perf_counter_ns()
    flags = []
    settings = get_settings()

    # Link calculations to the evidence submitted for those workflow stages.
    active_evidence = [item for item in claim.evidence_files
                       if item.status in {"ACTIVE", "PENDING_REVIEW"}]
    mass_balance_evidence_ids = [item.id for item in active_evidence if item.category in {
        "COLLECTION_WEIGHT_SLIP", "RECYCLER_RECEIPT", "PROCESSING_RECOVERY", "RECYCLING_CERTIFICATE",
    }]

    # Mass balance checks
    _effective_batches, effective_output, effective_recovered, effective_residual = _effective_processing(claim)
    flags.extend(
        check_mass_balance(
            declared_input_kg=claim.declared_weight_kg,
            received_input_kg=claim.received_weight_kg,
            processed_output_kg=effective_output if _effective_batches else claim.processed_output_kg,
            evidence_ids=mass_balance_evidence_ids,
            recovered_materials=effective_recovered if _effective_batches else (claim.mass_balance_details or {}).get("recovered_materials"),
            residual_waste_kg=effective_residual if _effective_batches else (claim.mass_balance_details or {}).get("residual_waste_kg"),
            tolerance_pct=get_settings().mass_balance_tolerance_pct,
        )
    )

    # Transport speed checks
    for leg in claim.transport_legs:
        transport_flags = check_transport_speed(
                origin_lat=leg.origin_lat,
                origin_lng=leg.origin_lng,
                dest_lat=leg.destination_lat,
                dest_lng=leg.destination_lng,
                departed_iso=leg.departed_at,
                arrived_iso=leg.arrived_at,
                vehicle_reg=leg.vehicle_registration,
                evidence_ids=[item.id for item in active_evidence
                              if item.category == "TRANSPORT_CHALLAN"
                              or (item.linked_entity_type == "TRANSPORT_LEG"
                                  and str(item.linked_entity_id) == str(leg.id))],
                max_speed_kmh=settings.max_hgv_speed_kmh,
            )
        for item in transport_flags:
            item.related_record_ids = [str(leg.id)]
        flags.extend(transport_flags)

    # The claim relationship is the source of truth for ownership. Hash matches
    # are then searched across all claims so reused files are detected globally.
    claim_evidence = list(claim.evidence_files)
    evidence_records = [
        {
            "id": item.id,
            "claim_id": item.claim_id,
            "sha256": item.sha256,
            "filename": item.filename,
            "extracted_data": item.extracted_data,
            "source": item.source,
            "category": item.category,
            "status": item.status,
        }
        for item in claim_evidence
    ]
    flags.extend(check_evidence_ownership(claim.id, evidence_records))
    flags.extend(check_stage_evidence(
        evidence_records,
        receipt_confirmed=claim.received_at is not None,
        processing_completed=claim.processing_completed_at is not None,
    ))
    # Check for suspicious evidence replacements
    replacement_records = [
        {
            "id": item.id,
            "logical_id": getattr(item, "logical_id", item.id),
            "sha256": item.sha256,
            "status": getattr(item, "status", "ACTIVE"),
        }
        for item in claim_evidence
    ]
    flags.extend(check_evidence_replacements(
        replacement_records,
        claim_status=claim.status,
        has_verification_result=claim.verification_result is not None,
    ))
    hashes = {item.sha256 for item in claim_evidence if item.sha256}
    if hashes:
        matching_query = db.query(Evidence).join(Claim, Claim.id == Evidence.claim_id).filter(Evidence.sha256.in_(hashes))
        matching_evidence = (matching_query.filter(_scope_filter(db, actor)).all()
                             if actor else matching_query.filter(Claim.id == claim.id).all())
        flags.extend(check_duplicate_evidence(
            claim.id,
            [
                {"id": item.id, "claim_id": item.claim_id, "sha256": item.sha256}
                for item in matching_evidence
            ],
        ))

    other_evidence_query = db.query(Evidence).join(Claim, Claim.id == Evidence.claim_id).filter(
        Evidence.claim_id != claim.id, Evidence.extracted_data.is_not(None))
    other_document_evidence = (other_evidence_query.filter(_scope_filter(db, actor)).all()
                               if actor else [])
    flags.extend(check_document_consistency(
        {
            "id": claim.id,
            "producer_name": claim.producer_name,
            "recycler_name": claim.recycler_name,
            "waste_category": claim.waste_category,
            "declared_weight_kg": claim.declared_weight_kg,
            "received_weight_kg": claim.received_weight_kg if claim.received_at else None,
            "received_at": _iso(claim.received_at) if claim.received_at else None,
            "processing_date": claim.processing_date,
            "collection_date": claim.collection_date,
        },
        evidence_records,
        [
            {
                "id": item.id,
                "claim_id": item.claim_id,
                "extracted_data": item.extracted_data,
            }
            for item in other_document_evidence
        ],
        quantity_tolerance_pct=settings.document_quantity_tolerance_pct,
        date_tolerance_days=settings.document_date_tolerance_days,
        mismatch_risk_contribution=settings.document_mismatch_risk_contribution,
        duplicate_identifier_risk_contribution=settings.duplicate_document_identifier_risk_contribution,
    ))

    previous_claims_query = (
        db.query(Claim)
        .options(joinedload(Claim.transport_legs), joinedload(Claim.evidence_files))
        .filter(Claim.id != claim.id)
    )
    previous_claims = previous_claims_query.filter(_scope_filter(db, actor)).all() if actor else []

    def match_record(item: Claim) -> dict:
        return {
            "id": item.id,
            "producer_name": item.producer_name,
            "producer_registration_number": item.producer_registration_number,
            "recycler_name": item.recycler_name,
            "recycler_registration_number": item.recycler_registration_number,
            "waste_category": item.waste_category,
            "declared_weight_kg": item.declared_weight_kg,
            "collection_date": item.collection_date,
            "vehicle_registrations": [leg.vehicle_registration for leg in item.transport_legs],
            "departed_at": [leg.departed_at for leg in item.transport_legs],
            "evidence_files": [
                {"id": evidence.id, "filename": evidence.filename, "sha256": evidence.sha256}
                for evidence in item.evidence_files
            ],
        }

    flags.extend(check_duplicate_claims(
        match_record(claim),
        [match_record(item) for item in previous_claims],
        similarity_threshold_pct=settings.duplicate_claim_similarity_threshold_pct,
        quantity_tolerance_pct=settings.duplicate_claim_quantity_tolerance_pct,
        date_window_days=settings.duplicate_claim_date_window_days,
        risk_contribution=settings.duplicate_claim_risk_contribution,
    ))

    duration_ms = max(1, (time.perf_counter_ns() - start) // 1_000_000)

    existing = claim.verification_result
    previous_flags = list((existing.flags or []) if existing else [])
    previous_by_id = {item.get("flag_id"): item for item in previous_flags if item.get("flag_id")}
    now = datetime.now(timezone.utc)

    def flag_id(flag) -> str:
        identity = {
            "claim_id": claim.id,
            "rule": flag.rule_reference or flag.code,
            "code": flag.code,
            "evidence_ids": sorted(flag.evidence_ids),
            "related_claim_ids": sorted(flag.related_claim_ids),
            "related_record_ids": sorted(flag.related_record_ids),
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()[:24]
        return f"flg_{digest}"

    scored = [(item, flag_id(item)) for item in flags
              if previous_by_id.get(flag_id(item), {}).get("status") != "DISMISSED"]
    risk_score, risk_level, scored_contributions = score_flags([item for item, _ in scored])
    contribution_by_id = {identity: contribution for (_, identity), contribution in zip(scored, scored_contributions)}

    # Build per-flag dicts and score breakdowns
    flag_dicts = []
    rule_contributions = []
    geo_score = 0
    mb_score = 0
    duplicate_score = 0
    document_score = 0

    active_ids = set()
    for f in flags:
        identity = flag_id(f)
        active_ids.add(identity)
        previous = previous_by_id.get(identity, {})
        if previous.get("status") == "DISMISSED":
            flag_dicts.append(previous)
            continue
        contribution = contribution_by_id.get(identity, 0)
        definition = get_rule_definition(f.rule_reference)
        flag_dicts.append({
            "flag_id": identity,
            "rule_version": settings.verification_ruleset_version,
            "detected_at": previous.get("detected_at") or _iso(now),
            "status": "ACTIVE",
            "code": f.code,
            "layer": f.layer,
            "severity": f.severity,
            "description": f.description,
            "evidence_ids": f.evidence_ids,
            "rule_reference": f.rule_reference,
            "actual_values": f.actual_values,
            "expected_relationship": f.expected_relationship,
            "difference_kg": f.difference_kg,
            "variance_pct": f.variance_pct,
            "risk_contribution": contribution,
            "score_delta": contribution,
            "related_claim_ids": f.related_claim_ids,
            "related_record_ids": f.related_record_ids,
            "matched_fields": f.matched_fields,
            "rule_name": definition.name if definition else f.code.replace("_", " ").title(),
            "rule_category": definition.category if definition else "uncatalogued",
            "rationale": definition.rationale if definition else "This detector is not yet documented in the rule catalog.",
            "recommended_action": definition.reviewer_action if definition else "Review the claim and supporting records.",
        })
        rule_contributions.append({
            "rule_id": f.rule_reference or f.code,
            "label": f.code.replace("_", " ").lower(),
            "score_delta": contribution,
            "triggered": True,
            "details": f.description,
        })
        if f.layer == "GEOSPATIAL":
            geo_score += contribution
        elif f.layer == "MASS_BALANCE":
            mb_score += contribution
        elif f.layer == "DUPLICATE":
            duplicate_score += contribution
        elif f.layer == "DOCUMENT":
            document_score += contribution

    # Retain disappeared findings as resolved history instead of silently
    # deleting them from the current verification record.
    for previous in previous_flags:
        identity = previous.get("flag_id")
        if not identity or identity in active_ids:
            continue
        if previous.get("status") in {"DISMISSED", "RESOLVED"}:
            flag_dicts.append(previous)
            continue
        flag_dicts.append({
            **previous,
            "status": "RESOLVED",
            "risk_contribution": 0,
            "score_delta": 0,
            "resolved_at": _iso(now),
            "resolution_reason": "Condition was not detected during re-evaluation.",
            "resolution_type": "AUTO_CLEARED",
        })

    for item in claim_evidence:
        related_flags = [f for f in flags if item.id in f.evidence_ids]
        if any(f.code in EVIDENCE_MISMATCH_RULES for f in related_flags):
            item.verification_status = "DISCREPANCY_DETECTED"
        elif item.extracted_data and CHECKED_DOCUMENT_FIELDS.intersection(item.extracted_data):
            item.verification_status = "METADATA_CONSISTENT"
        else:
            item.verification_status = "PENDING_HUMAN_REVIEW"

    explainability = {
        "document_score": document_score,
        "image_score": None,
        "geospatial_score": geo_score,
        "mass_balance_score": mb_score,
        "duplicate_score": duplicate_score,
        "graph_score": None,
        "ml_anomaly_score": None,
        "rule_contributions": rule_contributions,
    }

    # Upsert
    active_items = [item for item in flag_dicts if item["status"] == "ACTIVE"]
    active_signature = sorted((item["flag_id"], item["risk_contribution"],
                               json.dumps({"description": item["description"], "actual_values": item["actual_values"],
                                           "expected_relationship": item["expected_relationship"]},
                                          sort_keys=True, default=str))
                              for item in active_items)
    old_active_signature = sorted((item.get("flag_id"), item.get("risk_contribution", item.get("score_delta", 0)),
                                   json.dumps({"description": item.get("description"), "actual_values": item.get("actual_values", {}),
                                               "expected_relationship": item.get("expected_relationship", "")},
                                              sort_keys=True, default=str))
                                  for item in previous_flags if item.get("status", "ACTIVE") == "ACTIVE")
    score_history = list((existing.explainability or {}).get("score_history", []) if existing else [])
    previous_score_state = ({"risk_score": existing.risk_score, "risk_level": existing.risk_level}
                            if existing else None)
    snapshot_changed = not existing or risk_score != existing.risk_score or active_signature != old_active_signature
    if snapshot_changed:
        score_history.append({
            "calculated_at": _iso(now), "score": risk_score, "risk_band": risk_level,
            "ruleset_version": settings.verification_ruleset_version,
            "active_flag_ids": [item[0] for item in active_signature],
            "active_flags": [{"flag_id": item["flag_id"], "rule_id": item["rule_reference"],
                              "code": item["code"], "contribution": item["risk_contribution"],
                              "description": item["description"], "actual_values": item["actual_values"]}
                             for item in active_items],
        })
    explainability["score_history"] = score_history

    if existing:
        existing.risk_score = risk_score
        existing.risk_level = risk_level
        existing.flags = flag_dicts
        existing.processing_duration_ms = duration_ms
        existing.verified_at = now
        existing.model_version = get_settings().verification_model_version
        existing.explainability = explainability
    else:
        db.add(VRModel(
            claim_id=claim.id,
            risk_score=risk_score,
            risk_level=risk_level,
            flags=flag_dicts,
            processing_duration_ms=duration_ms,
            verified_at=now,
            model_version=get_settings().verification_model_version,
            explainability=explainability,
        ))
    _append_audit(claim, "VERIFICATION_COMPLETED", actor, db=db,
                  previous=({**previous_score_state,
                             "active_flag_ids": [item[0] for item in old_active_signature]}
                            if previous_score_state else None),
                  values={"risk_score": risk_score, "risk_level": risk_level,
                          "ruleset_version": settings.verification_ruleset_version,
                          "active_flag_ids": [item["flag_id"] for item in flag_dicts if item.get("status") == "ACTIVE"],
                          "flag_codes": [item["code"] for item in flag_dicts if item.get("status") == "ACTIVE"]},
                  related_flag_id=flag_dicts[0]["flag_id"] if flag_dicts else None) if snapshot_changed else None


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/", status_code=201)
def create_claim(
    body: ClaimCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_producer),
):
    """Submit a new recycling claim. Verification runs automatically."""
    claim_id = f"clm_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    ref = _allocate_claim_reference(db, now.year)

    facility_id = body.recycler_facility_id
    selected_member_id = None
    if facility_id is None and body.recycler_user_id:
        # Older clients can select a recycler employee, but the facility is derived
        # exclusively through that employee's verified membership.
        membership = db.query(FacilityMembership).filter(
            FacilityMembership.user_id == body.recycler_user_id,
            FacilityMembership.active.is_(True), FacilityMembership.verified.is_(True)
        ).first()
        if membership:
            facility_id, selected_member_id = membership.facility_id, body.recycler_user_id
    facility = db.get(RecyclerFacility, facility_id) if facility_id else None
    if (facility is None or facility.authorization_status != "AUTHORIZED"
            or body.waste_category not in (facility.permitted_waste_categories or [])):
        raise HTTPException(status_code=422, detail="Select an authorized facility permitted to process this waste category")
    assigned_memberships = db.query(FacilityMembership).join(
        User, User.id == FacilityMembership.user_id
    ).filter(
        FacilityMembership.facility_id == facility.id,
        FacilityMembership.active.is_(True),
        FacilityMembership.verified.is_(True),
        User.is_active.is_(True),
        User.role == RECYCLER_EMPLOYEE,
    ).order_by(User.username).all()
    if not assigned_memberships:
        raise HTTPException(status_code=422, detail="This facility has no active, verified recycler account to receive claims")
    assigned_user_ids = {membership.user_id for membership in assigned_memberships}
    if body.recycler_user_id:
        if body.recycler_user_id not in assigned_user_ids:
            raise HTTPException(status_code=422, detail="The selected recycler account is not assigned to this facility")
        selected_member_id = body.recycler_user_id
    elif len(assigned_memberships) == 1:
        # Record a direct assignee for single-account facilities. Facility scoping
        # still lets additional verified employees at the same company collaborate.
        selected_member_id = assigned_memberships[0].user_id
    jurisdiction_matches = []
    for area in db.query(GovernmentJurisdiction).all():
        try:
            if area.boundary and _point_in_boundary(body.origin_lng, body.origin_lat, area.boundary):
                jurisdiction_matches.append(area.id)
        except (TypeError, ValueError):
            continue
    # Overlapping/ambiguous and unmapped areas are left unassigned for administrative review.
    jurisdiction_id = jurisdiction_matches[0] if len(jurisdiction_matches) == 1 else None

    claim = Claim(
        id=claim_id,
        owner_user_id=current_user.id,
        recycler_user_id=selected_member_id,
        recycler_facility_id=facility.id,
        jurisdiction_id=jurisdiction_id,
        legacy_audit_migrated=True,
        reference_number=ref,
        status="AWAITING_RECYCLER_CONFIRMATION",
        producer_name=body.producer_name,
        producer_registration_number=body.producer_registration_number,
        recycler_name=facility.name,
        recycler_registration_number=facility.registration_number,
        waste_category=body.waste_category,
        waste_subcategories=body.waste_subcategories,
        declared_weight_kg=body.declared_weight_kg,
        received_weight_kg=0,
        processed_output_kg=0,
        mass_balance_details={"recovered_materials": [], "residual_waste_kg": None,
                              "processing_batches": [], "audit_history": []},
        collection_date=body.collection_date,
        origin_address=body.origin_address,
        destination_address=body.destination_address,
        notes=body.notes,
        submitted_at=now,
        updated_at=now,
    )

    leg = TransportLeg(
        claim_id=claim_id,
        vehicle_registration=body.vehicle_registration,
        driver_name=body.driver_name,
        origin_lat=body.origin_lat,
        origin_lng=body.origin_lng,
        origin_timestamp=body.departed_at,
        origin_accuracy_m=10.0,
        destination_lat=body.destination_lat,
        destination_lng=body.destination_lng,
        destination_timestamp=body.arrived_at,
        destination_accuracy_m=10.0,
        declared_weight_kg=body.declared_weight_kg,
        departed_at=body.departed_at,
        arrived_at=body.arrived_at,
    )

    db.add(claim)
    db.add(leg)
    _append_audit(claim, "CLAIM_SUBMITTED", current_user, db=db, role="PRODUCER",
                  values={"producer_name": claim.producer_name, "recycler_facility_id": facility.id,
                          "recycler_user_id": selected_member_id,
                          "jurisdiction_id": jurisdiction_id, "waste_category": claim.waste_category,
                          "declared_weight_kg": claim.declared_weight_kg,
                          "collection_date": claim.collection_date,
                          "origin_address": claim.origin_address,
                          "destination_address": claim.destination_address,
                          "transport": {"vehicle_registration": leg.vehicle_registration,
                                        "driver_name": leg.driver_name,
                                        "origin": [leg.origin_lat, leg.origin_lng],
                                        "destination": [leg.destination_lat, leg.destination_lng],
                                        "departed_at": leg.departed_at, "arrived_at": leg.arrived_at}})
    db.flush()

    db.commit()

    return _build_response(_load_claim(claim_id, db, current_user))


@router.get("/")
def list_claims(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str = Query("submitted_at", pattern="^(submitted_at|status|reference_number)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all claims, optionally filtered by status."""
    sort_column = {
        "submitted_at": Claim.submitted_at,
        "status": Claim.status,
        "reference_number": Claim.reference_number,
    }[sort_by]
    sort_expression = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    query = (
        db.query(Claim)
        .options(
            joinedload(Claim.transport_legs),
            joinedload(Claim.evidence_files),
            joinedload(Claim.verification_result),
        )
        .order_by(sort_expression, Claim.id.asc())
    )
    query = query.filter(_scope_filter(db, current_user))
    if status and status != "ALL":
        query = query.filter(Claim.status == status)

    total = query.order_by(None).count()
    results = query.offset((page - 1) * page_size).limit(page_size).all()
    # joinedload can produce duplicates — deduplicate by claim ID
    seen: dict[str, Claim] = {}
    for c in results:
        if c.id not in seen:
            seen[c.id] = c
    return {"items": [_build_response(c) for c in seen.values()], "total": total,
            "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size}


@router.get("/recyclers")
def list_recyclers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_producer),
):
    """List authorized recycler facilities available for assignment."""
    facilities = db.query(RecyclerFacility).join(
        FacilityMembership, FacilityMembership.facility_id == RecyclerFacility.id
    ).join(
        User, User.id == FacilityMembership.user_id
    ).filter(
        RecyclerFacility.authorization_status == "AUTHORIZED",
        FacilityMembership.active.is_(True),
        FacilityMembership.verified.is_(True),
        User.is_active.is_(True),
        User.role == RECYCLER_EMPLOYEE,
    ).distinct().order_by(RecyclerFacility.name).all()
    return [
        {"id": facility.id, "organisation": facility.name, "display_name": facility.name,
         "registration_number": facility.registration_number}
        for facility in facilities
    ]


@router.get("/assigned")
def list_assigned_claims(
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List claims assigned to facilities with verified employee membership."""
    if current_user.role != RECYCLER_EMPLOYEE:
        raise HTTPException(status_code=403, detail="Recycler employee role required")
    query = (
        db.query(Claim)
        .options(
            joinedload(Claim.transport_legs),
            joinedload(Claim.evidence_files),
            joinedload(Claim.verification_result),
        )
        .filter(_scope_filter(db, current_user))
        .order_by(Claim.submitted_at.desc(), Claim.id.asc())
    )
    if page is not None:
        total = query.order_by(None).count()
        claims = query.offset((page - 1) * page_size).limit(page_size).all()
        return {"items": [_build_response(claim) for claim in claims], "total": total,
                "page": page, "page_size": page_size,
                "pages": (total + page_size - 1) // page_size}
    claims = query.all()
    return [_build_response(claim) for claim in claims]


@router.get("/geocode")
def geocode_address(
    query: str = Query(min_length=3, max_length=300),
    current_user: User = Depends(get_current_user),
):
    """Find matching coordinates for a user-entered claim address."""
    try:
        return {"results": find_locations(query)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/verification/rules")
def get_verification_rule_catalog(current_user: User = Depends(require_government_official)):
    """Expose the implemented rule catalog to authorized government reviewers."""
    settings = get_settings()
    try:
        configured_weights = json.loads(settings.risk_rule_weights_json or "{}")
        if not isinstance(configured_weights, dict):
            configured_weights = {}
    except (TypeError, ValueError):
        configured_weights = {}
    try:
        group_caps = json.loads(settings.risk_group_caps_json or "{}")
        if not isinstance(group_caps, dict):
            group_caps = {}
    except (TypeError, ValueError):
        group_caps = {}
    return {
        "ruleset_version": settings.verification_ruleset_version or RULESET_VERSION,
        "score_range": [0, 100],
        "risk_bands": {
            "LOW": [0, settings.risk_band_low_max],
            "MEDIUM": [settings.risk_band_low_max + 1, settings.risk_band_medium_max],
            "HIGH": [settings.risk_band_medium_max + 1, settings.risk_band_high_max],
            "CRITICAL": [settings.risk_band_high_max + 1, 100],
        },
        "rules": [
            {"rule_id": rule.rule_id, "name": rule.name, "category": rule.category,
             "rationale": rule.rationale, "score_group": rule.score_group,
             "recommended_action": rule.reviewer_action, "blocking": rule.blocking,
             "enabled": rule.enabled,
             "default_contribution": DEFAULT_RULE_WEIGHTS.get(rule.rule_id),
             "configured_weight": configured_weights.get(rule.rule_id),
             "scoring_note": SCORING_NOTES.get(rule.rule_id, "Uses the detector contribution, then the configured score-group cap."),
             "group_cap": group_caps.get(rule.score_group, 100)}
            for rule in RULE_CATALOG.values()
        ],
    }


@router.get("/{claim_id}")
def get_claim(
    claim_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a single claim by ID."""
    return _build_response(_load_claim(claim_id, db, current_user))


@router.get("/{claim_id}/audit")
def get_claim_audit_history(
    claim_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    claim = _load_claim(claim_id, db, current_user)
    events = list(claim.audit_events)
    integrity = verify_event_chain_diagnostics(events)
    return {"claim_id": claim.id, "events": [_event_response(event) for event in events],
            "chain_valid": integrity["valid"], "integrity": integrity}


@router.post("/{claim_id}/flags/{flag_id}/dismiss")
def dismiss_verification_flag(
    claim_id: str,
    flag_id: str,
    body: FlagDismissBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_government_official),
):
    """Dismiss a finding with a recorded officer rationale and recalculate risk."""
    claim = _load_claim(claim_id, db, current_user)
    result = claim.verification_result
    if result is None:
        raise HTTPException(status_code=404, detail="Verification result not found")
    flag_list = [dict(item) for item in (result.flags or [])]
    finding = next((item for item in flag_list if item.get("flag_id") == flag_id), None)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if finding.get("status", "ACTIVE") != "ACTIVE":
        raise HTTPException(status_code=409, detail="Only an active finding can be dismissed")

    now = datetime.now(timezone.utc)
    previous = {"status": "ACTIVE", "risk_contribution": finding.get("risk_contribution", 0)}
    finding.update({
        "status": "DISMISSED", "risk_contribution": 0, "score_delta": 0,
        "resolved_at": _iso(now), "resolution_reason": body.reason,
        "resolution_type": "OFFICER_DISMISSED", "reviewed_by_user_id": current_user.id,
        "reviewed_by_name": current_user.display_name,
    })
    result.flags = flag_list
    _append_audit(claim, "VERIFICATION_FLAG_DISMISSED", current_user, db=db,
                  related_flag_id=flag_id, previous=previous,
                  values={"status": "DISMISSED", "resolution_reason": body.reason,
                          "reviewed_by_user_id": current_user.id})
    db.flush()
    _run_verification(claim, db, current_user)
    db.flush()
    return _build_response(claim)


@router.post("/{claim_id}/adjustments", status_code=201)
def create_mass_balance_adjustment(
    claim_id: str,
    body: MassBalanceAdjustmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    claim = _load_claim(claim_id, db, current_user)
    reason = body.reason.strip()
    if len(reason) < 5:
        raise HTTPException(status_code=422, detail="Adjustment reason must contain at least five non-space characters")
    if current_user.role != RECYCLER_EMPLOYEE:
        raise HTTPException(status_code=403, detail="Recycler employee role required")
    _assert_assigned_recycler(claim, current_user, db)
    db.query(Claim.id).filter(Claim.id == claim.id).with_for_update().first()
    if not claim.processing_completed_at or claim.status in {"APPROVED", "REJECTED", "VERIFIED"}:
        raise HTTPException(status_code=409, detail="Adjustments require a completed claim awaiting or undergoing review")
    original_batches, _, _, _ = _effective_processing(claim)
    batch = next((item for item in original_batches if item.get("batch_id") == body.processing_batch_id), None)
    if batch is None:
        raise HTTPException(status_code=422, detail="Processing batch not found")
    if body.field == "PROCESSED_OUTPUT":
        field_key, original = "processed_output_kg", float(batch.get("processed_output_kg", 0))
    elif body.field == "RESIDUAL_WASTE":
        field_key, original = "residual_waste_kg", float(batch.get("residual_waste_kg", 0))
    else:
        if body.material_index is None or body.material_index >= len(batch.get("recovered_materials", [])):
            raise HTTPException(status_code=422, detail="A valid recovered-material index is required")
        field_key = f"recovered_materials:{body.material_index}"
        original = float(batch["recovered_materials"][body.material_index].get("quantity_kg", 0))
    if original == body.corrected_quantity:
        raise HTTPException(status_code=422, detail="Corrected quantity must differ from the current quantity")
    if db.query(MassBalanceAdjustment).filter_by(
        claim_id=claim.id, processing_batch_id=body.processing_batch_id,
        field_key=field_key, review_status="PENDING",
    ).first():
        raise HTTPException(status_code=409, detail="A matching adjustment is already pending review")
    evidence_ids = list(dict.fromkeys(body.supporting_evidence_ids))
    if evidence_ids:
        count = db.query(Evidence.id).filter(Evidence.claim_id == claim.id, Evidence.id.in_(evidence_ids)).count()
        if count != len(evidence_ids):
            raise HTTPException(status_code=422, detail="Supporting evidence must belong to this claim")
    adjustment = MassBalanceAdjustment(
        id=f"adj_{uuid.uuid4().hex}", claim_id=claim.id,
        processing_batch_id=body.processing_batch_id, field_key=field_key,
        original_quantity=original, corrected_quantity=body.corrected_quantity,
        category=body.category, reason=reason,
        supporting_evidence_ids=evidence_ids, created_by_user_id=current_user.id,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None), review_status="PENDING",
    )
    db.add(adjustment)
    db.flush()
    _append_audit(claim, "MASS_BALANCE_ADJUSTMENT_REQUESTED", current_user, db=db,
        adjustment_id=adjustment.id, values={"batch_id": adjustment.processing_batch_id,
            "field": adjustment.field_key, "original_quantity": original,
            "corrected_quantity": body.corrected_quantity, "unit": "kg",
            "category": body.category, "supporting_evidence_ids": evidence_ids}, reason=adjustment.reason)
    db.commit()
    return _adjustment_response(db.get(MassBalanceAdjustment, adjustment.id))


@router.post("/{claim_id}/adjustments/{adjustment_id}/review")
def review_mass_balance_adjustment(
    claim_id: str,
    adjustment_id: str,
    body: MassBalanceAdjustmentReview,
    approve: bool = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_government_official),
):
    claim = _load_claim(claim_id, db, current_user)
    decision = body.decision.strip()
    if len(decision) < 3:
        raise HTTPException(status_code=422, detail="Review decision must contain at least three non-space characters")
    adjustment = db.query(MassBalanceAdjustment).filter_by(id=adjustment_id, claim_id=claim.id).with_for_update().first()
    if adjustment is None:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    if adjustment.review_status != "PENDING":
        raise HTTPException(status_code=409, detail="Adjustment has already been reviewed")
    previous_claim_status = claim.status
    adjustment.review_status = "APPROVED" if approve else "REJECTED"
    adjustment.reviewed_by_user_id = current_user.id
    adjustment.review_decision = decision
    adjustment.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _append_audit(claim, "MASS_BALANCE_ADJUSTMENT_APPROVED" if approve else "MASS_BALANCE_ADJUSTMENT_REJECTED",
        current_user, db=db, adjustment_id=adjustment.id,
        previous={"review_status": "PENDING", "reviewed_by_user_id": None},
        values={"review_status": adjustment.review_status, "reviewed_by_user_id": current_user.id,
                "reviewed_at": _iso(adjustment.reviewed_at), "decision": adjustment.review_decision},
        reason=adjustment.review_decision)
    if approve:
        db.flush()
        _run_verification(claim, db, current_user)
        db.flush()
        verification = db.query(VRModel).filter(VRModel.claim_id == claim.id).one()
        claim.status = "FLAGGED" if verification.risk_score > 0 else "PENDING"
        claim.updated_at = datetime.now(timezone.utc)
        _append_audit(claim, "CLAIM_STATUS_AFTER_ADJUSTMENT_REVIEW", current_user, db=db,
                      adjustment_id=adjustment.id, previous={"status": previous_claim_status},
                      values={"status": claim.status})
    db.commit()
    return {"adjustment": _adjustment_response(db.get(MassBalanceAdjustment, adjustment.id)),
            "claim": _build_response(_load_claim(claim_id, db, current_user))}


@router.post("/{claim_id}/receipt")
def confirm_receipt(
    claim_id: str,
    body: ReceiptConfirmation,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record receipt measurements without changing the producer declaration."""
    claim = _load_claim(claim_id, db, current_user)
    _assert_assigned_recycler(claim, current_user, db)
    correcting = claim.status == "AWAITING_CLARIFICATION" and claim.received_at is not None
    if claim.status != "AWAITING_RECYCLER_CONFIRMATION" and not correcting:
        raise HTTPException(status_code=409, detail=f"Cannot confirm receipt while claim is {claim.status}")

    received_at = body.received_at
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    previous_status = claim.status
    previous = {"received_weight_kg": claim.received_weight_kg if claim.received_at else None,
                "received_at": _iso(claim.received_at) if claim.received_at else None,
                "status": previous_status}
    claim.received_weight_kg = body.received_weight_kg
    claim.received_at = received_at
    if body.recycler_notes is not None:
        claim.recycler_notes = body.recycler_notes
    claim.clarification_reason = None
    _append_audit(claim, "RECEIPT_CORRECTED" if correcting else "RECEIPT_CONFIRMED",
                  current_user, db=db, role="RECYCLER", previous=previous,
                  values={"received_weight_kg": body.received_weight_kg, "received_at": _iso(received_at),
                          "status": "RECEIVED",
                          "recycler_notes": body.recycler_notes})
    claim.status = "RECEIVED"
    if correcting and claim.processing_completed_at:
        _run_verification(claim, db, current_user)
        db.flush()
        verification = db.query(VRModel).filter(VRModel.claim_id == claim.id).one()
        claim.status = "FLAGGED" if verification.risk_score > 0 else "PENDING"
    claim.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/processing")
def submit_processing(
    claim_id: str,
    body: ProcessingSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record recycler processing and run complete-transaction verification."""
    claim = _load_claim(claim_id, db, current_user)
    _assert_assigned_recycler(claim, current_user, db)
    previous_status = claim.status
    correcting = claim.status == "AWAITING_CLARIFICATION" and body.corrects_previous
    clarification_reply_to = claim.clarification_reason if correcting else None
    if claim.status not in {"RECEIVED", "PROCESSING", "AWAITING_CLARIFICATION"} or claim.received_at is None:
        raise HTTPException(status_code=409, detail="Confirm receipt before submitting processing results")
    if body.corrects_previous and not correcting:
        raise HTTPException(status_code=409, detail="Processing corrections require a clarification request")
    if correcting and db.query(MassBalanceAdjustment.id).filter_by(
        claim_id=claim.id, review_status="PENDING"
    ).first():
        raise HTTPException(status_code=409, detail="Resolve pending mass-balance adjustments before replacing processing batches")

    details = dict(claim.mass_balance_details or {})
    batches = list(details.get("processing_batches") or [])
    if body.batches is None:
        incoming = [{"batch_id": None, "processed_output_kg": body.processed_output_kg,
                     "recovered_materials": [{"material": "Recovered materials",
                                               "quantity_kg": body.recovered_materials_total_kg,
                                               "grade": "", "destination_facility": ""}],
                     "residual_waste_kg": body.residual_waste_kg, "processing_date": body.processing_date,
                     "notes": body.recycler_notes}]
    else:
        incoming = [item.model_dump() for item in body.batches]
    if correcting:
        previous_batches = batches
        batches = []
        _append_audit(claim, "PROCESSING_CORRECTION_REQUESTED", current_user, db=db,
                      role="RECYCLER", previous={"processing_batches": previous_batches},
                      values={"processing_batches": []}, replaced_batches=previous_batches,
                      reason=clarification_reply_to)
        details = dict(claim.mass_balance_details or {})
        details["processing_batches"] = []
    incoming_ids = [item.get("batch_id") for item in incoming if item.get("batch_id")]
    active_ids = {item.get("batch_id") for item in batches}
    if len(incoming_ids) != len(set(incoming_ids)) or active_ids.intersection(incoming_ids):
        raise HTTPException(status_code=422, detail="Processing batch IDs must be unique within the active record")
    submitted_at = _iso(datetime.now(timezone.utc))
    for item in incoming:
        batch_id = item.get("batch_id") or f"batch_{uuid.uuid4().hex[:10]}"
        record = {**item, "batch_id": batch_id, "submitted_at": submitted_at,
                  "submitted_by": _audit_actor(current_user, "RECYCLER")}
        batches.append(record)
        _append_audit(claim, "PROCESSING_BATCH_CORRECTED" if correcting else "PROCESSING_BATCH_SUBMITTED",
                      current_user, db=db, role="RECYCLER", batch_id=batch_id, values=record)
    processed_total = sum(float(item["processed_output_kg"]) for item in batches)
    recovered_totals: dict[tuple[str, str, str], dict] = {}
    for batch in batches:
        for material in batch.get("recovered_materials", []):
            key = (str(material.get("material", "Recovered materials")),
                   str(material.get("grade", "")), str(material.get("destination_facility", "")))
            entry = recovered_totals.setdefault(key, {"material": key[0], "grade": key[1],
                                                       "destination_facility": key[2], "quantity_kg": 0.0})
            entry["quantity_kg"] += float(material.get("quantity_kg", 0))
    residual_total = sum(float(item["residual_waste_kg"]) for item in batches)
    details = dict(claim.mass_balance_details or {})
    details.update({"processing_batches": batches, "recovered_materials": list(recovered_totals.values()),
                    "residual_waste_kg": residual_total})
    claim.mass_balance_details = details
    claim.processed_output_kg = processed_total
    claim.processing_date = incoming[-1]["processing_date"] if incoming else claim.processing_date
    if body.recycler_notes is not None:
        claim.recycler_notes = body.recycler_notes
    claim.processing_completed_at = datetime.now(timezone.utc) if body.finalize else None
    claim.clarification_reason = None if correcting else claim.clarification_reason
    claim.status = "READY_FOR_VERIFICATION" if body.finalize else "PROCESSING"
    claim.updated_at = datetime.now(timezone.utc)
    if not body.finalize:
        _append_audit(claim, "PROCESSING_SUBMITTED", current_user, db=db,
                      previous={"status": previous_status}, values={"status": "PROCESSING",
                          "processing_batches": [item["batch_id"] for item in incoming]})
        if correcting:
            _append_audit(claim, "CLARIFICATION_RESPONSE_SUBMITTED", current_user, db=db,
                          values={"batch_ids": [item["batch_id"] for item in incoming]},
                          reason=clarification_reply_to)
        db.commit()
        return _build_response(_load_claim(claim_id, db, current_user))
    db.flush()

    _run_verification(claim, db, current_user)
    db.flush()
    verification = db.query(VRModel).filter(VRModel.claim_id == claim.id).one()
    claim.status = "FLAGGED" if verification.risk_score > 0 else "PENDING"
    _append_audit(claim, "PROCESSING_SUBMITTED", current_user, db=db,
                  previous={"status": previous_status}, values={"status": claim.status,
                      "processing_batches": [item["batch_id"] for item in incoming]})
    if correcting:
        _append_audit(claim, "CLARIFICATION_RESPONSE_SUBMITTED", current_user, db=db,
                      values={"batch_ids": [item["batch_id"] for item in incoming]},
                      reason=clarification_reply_to)
    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/approve")
def approve_claim(
    claim_id: str,
    body: ApproveBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_government_official),
):
    """Government official approves a pending claim."""
    claim = _load_claim(claim_id, db, current_user)
    if claim.status not in {"PENDING", "FLAGGED"} or claim.processing_completed_at is None:
        raise HTTPException(400, f"Cannot approve a {claim.status} claim")

    previous_status = claim.status
    claim.status = "APPROVED"
    claim.updated_at = datetime.now(timezone.utc)
    stamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
    note = f"Approved by {current_user.display_name} on {stamp}."
    claim.notes = f"{claim.notes}\n{note}" if claim.notes else note
    _append_audit(claim, "CLAIM_APPROVED", current_user, db=db, role="GOV_OFFICIAL",
                  previous={"status": previous_status}, values={"status": "APPROVED"},
                  official_name=current_user.display_name)

    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/reject")
def reject_claim(
    claim_id: str,
    body: RejectBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_government_official),
):
    """Government official rejects a pending claim with a reason."""
    claim = _load_claim(claim_id, db, current_user)
    if claim.status not in {"PENDING", "FLAGGED"} or claim.processing_completed_at is None:
        raise HTTPException(400, f"Cannot reject a {claim.status} claim")

    previous_status = claim.status
    claim.status = "REJECTED"
    claim.updated_at = datetime.now(timezone.utc)
    stamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
    note = f"Rejected by {current_user.display_name} on {stamp}. Reason: {body.reason}"
    claim.notes = f"{claim.notes}\n{note}" if claim.notes else note
    _append_audit(claim, "CLAIM_REJECTED", current_user, db=db, role="GOV_OFFICIAL",
                  official_name=current_user.display_name,
                  previous={"status": previous_status}, values={"status": "REJECTED"},
                  reason=body.reason)

    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/clarification")
def request_claim_clarification(
    claim_id: str,
    body: RequestClarificationBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_government_official),
):
    """Return a submitted transaction to its parties for an auditable correction."""
    claim = _load_claim(claim_id, db, current_user)
    if claim.status not in {"PENDING", "FLAGGED"}:
        raise HTTPException(status_code=409, detail="Clarification can only be requested on a claim under review")
    previous_status = claim.status
    claim.status = "AWAITING_CLARIFICATION"
    claim.clarification_reason = body.reason.strip()
    claim.updated_at = datetime.now(timezone.utc)
    _append_audit(claim, "CLARIFICATION_REQUESTED", current_user, db=db, role="GOV_OFFICIAL",
                  previous={"status": previous_status},
                  values={"status": "AWAITING_CLARIFICATION", "clarification_reason": claim.clarification_reason},
                  reason=claim.clarification_reason)
    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/audit-note")
def record_claim_audit_note(
    claim_id: str,
    body: AuditNoteBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_government_official),
):
    """Record a routine audit or investigation note without changing claim status."""
    note = body.note.strip()
    if len(note) < 3:
        raise HTTPException(status_code=422, detail="Audit note must contain at least three non-space characters")
    claim = _load_claim(claim_id, db, current_user)
    _append_audit(
        claim,
        "ROUTINE_AUDIT_RECORDED" if body.audit_type == "ROUTINE" else "INVESTIGATION_NOTE_RECORDED",
        current_user,
        db=db,
        role="GOV_OFFICIAL",
        note=note,
    )
    claim.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/verify")
def trigger_verification(
    claim_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run the verification engine on an existing claim."""
    claim = _load_claim(claim_id, db, current_user)
    _run_verification(claim, db, current_user)
    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/evidence", status_code=201)
def upload_evidence(
    claim_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    category: Annotated[str, Form()] = "OTHER_SUPPORTING",
    document_data: str | None = Form(default=None),
    linked_entity_type: Annotated[str | None, Form()] = None,
    linked_entity_id: Annotated[str | None, Form()] = None,
):
    """Store stage-specific evidence and its claim-linked submitter metadata."""
    from app.services.storage import get_storage_backend
    from app.models import EvidenceVersion

    claim = _load_claim(claim_id, db, current_user)
    if category not in EVIDENCE_CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown evidence category")
    if current_user.role not in {PRODUCER, RECYCLER_EMPLOYEE}:
        raise HTTPException(status_code=403, detail="Government officials cannot upload claim evidence")
    if current_user.role == PRODUCER and claim.owner_user_id == current_user.id:
        if claim.status != "AWAITING_RECYCLER_CONFIRMATION":
            raise HTTPException(status_code=409, detail="Producer evidence can only be added before recycler confirmation")
        evidence_source = "PRODUCER"
    else:
        if current_user.role != RECYCLER_EMPLOYEE:
            raise HTTPException(status_code=403, detail="This account cannot upload claim evidence")
        _assert_assigned_recycler(claim, current_user, db)
        if claim.status in {"APPROVED", "VERIFIED", "REJECTED"}:
            raise HTTPException(status_code=409, detail="Evidence cannot be added after a government decision")
        evidence_source = "RECYCLER"

    category_owner = EVIDENCE_CATEGORIES[category]
    if category_owner not in {"EITHER", evidence_source}:
        raise HTTPException(status_code=403, detail="This evidence category belongs to the other party")
    if claim.status in {"APPROVED", "VERIFIED", "REJECTED"}:
        raise HTTPException(status_code=409, detail="Evidence cannot be added after a government decision")
    if category == "RECYCLER_RECEIPT" and claim.received_at is None:
        raise HTTPException(status_code=409, detail="Confirm receipt before uploading destination weight evidence")
    if category in {"PROCESSING_RECOVERY", "RECYCLING_CERTIFICATE"} and claim.processing_completed_at is None:
        raise HTTPException(status_code=409, detail="Processing must be completed before uploading this evidence")

    if linked_entity_type is None and linked_entity_id is None:
        linked_entity_type, linked_entity_id = "CLAIM", claim.id
    elif not linked_entity_type or not linked_entity_id:
        raise HTTPException(status_code=422, detail="Both linked entity type and ID must be provided")
    elif linked_entity_type in {"CLAIM", "RECEIPT", "RESIDUAL_WASTE"}:
        if linked_entity_id != claim.id or (linked_entity_type == "RECEIPT" and claim.received_at is None):
            raise HTTPException(status_code=422, detail="Linked claim or operational record is not present")
    elif linked_entity_type == "TRANSPORT_LEG":
        if db.query(TransportLeg).filter_by(id=linked_entity_id, claim_id=claim.id).first() is None:
            raise HTTPException(status_code=422, detail="Transport leg does not belong to this claim")
    elif linked_entity_type == "PROCESSING_BATCH":
        batches = (claim.mass_balance_details or {}).get("processing_batches") or []
        if not any(str(batch.get("batch_id")) == linked_entity_id for batch in batches if isinstance(batch, dict)):
            raise HTTPException(status_code=422, detail="Processing batch does not belong to this claim")
    else:
        raise HTTPException(status_code=422, detail="Unsupported evidence link type")

    content, original_name, suffix, expected_mime, evidence_type, extracted_data = _validate_evidence_file(
        file, document_data
    )

    evidence_id = f"ev_{uuid.uuid4().hex[:12]}"
    logical_id = f"evl_{uuid.uuid4().hex[:12]}"
    digest = hashlib.sha256(content).hexdigest()
    storage = get_storage_backend()
    storage_key = storage.save(claim_id, suffix, content)

    try:
        evidence = Evidence(
            id=evidence_id,
            claim_id=claim_id,
            claim=claim,
            logical_id=logical_id,
            type=evidence_type,
            filename=original_name[:500],
            file_path=storage_key,
            storage_key=storage_key,
            sha256=digest,
            mime_type=expected_mime,
            size_bytes=len(content),
            source=evidence_source,
            category=category,
            uploaded_by_user_id=current_user.id,
            uploader_role=current_user.role,
            uploader=current_user,
            verification_status=("METADATA_PROVIDED" if "UPLOADER_PROVIDED" in (extracted_data or {}).get("_provenance", {}).get("field_sources", {}).values()
                                 else "PENDING_HUMAN_REVIEW" if (extracted_data or {}).get("_provenance", {}).get("extraction_status") in {"FAILED", "MANUAL_REVIEW"}
                                 else "EXTRACTED_UNVERIFIED" if extracted_data else "PENDING_HUMAN_REVIEW"),
            extraction_status=((extracted_data or {}).get("_provenance", {}).get("extraction_status") or "COMPLETED") if extracted_data else "PENDING",
            extracted_data=extracted_data,
            extraction_provenance=(extracted_data or {}).get("_provenance"),
            status="ACTIVE",
            version_number=1,
            linked_entity_type=linked_entity_type,
            linked_entity_id=linked_entity_id,
        )
        db.add(evidence)
        db.flush()

        # Create initial version record
        version = EvidenceVersion(
            id=f"evv_{uuid.uuid4().hex[:12]}",
            evidence_id=evidence_id,
            version_number=1,
            storage_key=storage_key,
            sha256=digest,
            size_bytes=len(content),
            mime_type=expected_mime,
            filename=original_name[:500],
            uploaded_by_user_id=current_user.id,
            uploader_role=current_user.role,
            status="ACTIVE",
            extracted_data=extracted_data,
            extraction_provenance=(extracted_data or {}).get("_provenance"),
        )
        db.add(version)
        db.flush()

        _append_audit(claim, "EVIDENCE_UPLOADED", current_user, db=db, evidence_id=evidence.id,
                      role=evidence_source, category=category, sha256=digest, source=evidence_source,
                      values={"logical_id": logical_id, "version_number": 1,
                              "filename": original_name[:500], "size_bytes": len(content),
                              "linked_entity_type": linked_entity_type,
                              "linked_entity_id": linked_entity_id})
        _run_verification(claim, db, current_user)
        if claim.processing_completed_at and claim.status in {"PENDING", "FLAGGED"}:
            verification = db.query(VRModel).filter(VRModel.claim_id == claim.id).one()
            claim.status = "FLAGGED" if verification.risk_score > 0 else "PENDING"
        db.commit()
    except Exception as exc:
        db.rollback()
        storage.delete(storage_key)
        if isinstance(exc, OperationalError):
            raise HTTPException(status_code=409, detail="Evidence changed concurrently; reload and retry") from exc
        raise

    return _build_response(_load_claim(claim_id, db, current_user))


@router.post("/{claim_id}/evidence/{evidence_id}/replace", status_code=201)
def replace_evidence(
    claim_id: str,
    evidence_id: str,
    file: UploadFile = File(...),
    replacement_reason: str = Form(..., min_length=3, max_length=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    document_data: str | None = Form(default=None),
):
    """Replace an existing evidence document, preserving the previous version."""
    from app.services.storage import get_storage_backend
    from app.models import EvidenceVersion

    claim = _load_claim(claim_id, db, current_user)
    old_evidence = (
        db.query(Evidence)
        .filter(Evidence.id == evidence_id, Evidence.claim_id == claim_id, Evidence.status == "ACTIVE")
        .first()
    )
    if not old_evidence:
        raise HTTPException(status_code=404, detail="Active evidence not found")

    replacement_reason = replacement_reason.strip()
    if len(replacement_reason) < 3:
        raise HTTPException(status_code=422, detail="Replacement reason must contain at least three non-whitespace characters")

    # Authorization: same rules as upload
    if current_user.role not in {PRODUCER, RECYCLER_EMPLOYEE}:
        raise HTTPException(status_code=403, detail="Cannot replace evidence with this role")
    if current_user.role == PRODUCER:
        if claim.owner_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not the claim owner")
        if old_evidence.source != "PRODUCER":
            raise HTTPException(status_code=403, detail="Producers can only replace evidence they are authorized to manage")
        if claim.status != "AWAITING_RECYCLER_CONFIRMATION":
            raise HTTPException(status_code=409, detail="Producer can only replace evidence before recycler confirmation")
        evidence_source = "PRODUCER"
    else:
        _assert_assigned_recycler(claim, current_user, db)
        if old_evidence.source != "RECYCLER":
            raise HTTPException(status_code=403, detail="Recyclers can only replace recycler evidence")
        evidence_source = "RECYCLER"

    # A reviewed or approved claim can be reopened by an authorized party,
    # but the replacement remains pending review until the officer rechecks it.
    requires_review = claim.status in {"PENDING", "FLAGGED", "APPROVED", "VERIFIED"} or claim.verification_result is not None
    if claim.status == "REJECTED":
        raise HTTPException(status_code=409, detail="Evidence cannot be replaced on a rejected claim")
    if EVIDENCE_CATEGORIES.get(old_evidence.category) not in {"EITHER", evidence_source}:
        raise HTTPException(status_code=403, detail="This evidence category belongs to the other party")

    content, original_name, suffix, expected_mime, evidence_type, extracted_data = _validate_evidence_file(
        file, document_data
    )

    new_evidence_id = f"ev_{uuid.uuid4().hex[:12]}"
    digest = hashlib.sha256(content).hexdigest()
    storage = get_storage_backend()
    storage_key = storage.save(claim_id, suffix, content)
    new_version_number = old_evidence.version_number + 1

    try:
        changed = db.query(Evidence).filter(Evidence.id == old_evidence.id,
            Evidence.status == "ACTIVE").update({"status": "SUPERSEDED",
                "replaced_by_id": new_evidence_id, "replacement_reason": replacement_reason},
                synchronize_session=False)
        if changed != 1:
            raise HTTPException(status_code=409, detail="Evidence was replaced by another request")
        db.refresh(old_evidence)
        # Supersede old evidence
        old_evidence.status = "SUPERSEDED"
        old_evidence.replaced_by_id = new_evidence_id
        old_evidence.replacement_reason = replacement_reason

        # Mark old version as superseded
        old_version = (
            db.query(EvidenceVersion)
            .filter(EvidenceVersion.evidence_id == old_evidence.id, EvidenceVersion.status == "ACTIVE")
            .first()
        )
        if old_version:
            old_version.status = "SUPERSEDED"

        # Create new evidence record
        new_status = "PENDING_REVIEW" if requires_review else "ACTIVE"
        new_evidence = Evidence(
            id=new_evidence_id,
            claim_id=claim_id,
            claim=claim,
            logical_id=old_evidence.logical_id,
            type=evidence_type,
            filename=original_name[:500],
            file_path=storage_key,
            storage_key=storage_key,
            sha256=digest,
            mime_type=expected_mime,
            size_bytes=len(content),
            source=evidence_source,
            category=old_evidence.category,
            uploaded_by_user_id=current_user.id,
            uploader_role=current_user.role,
            uploader=current_user,
            verification_status=("METADATA_PROVIDED" if "UPLOADER_PROVIDED" in (extracted_data or {}).get("_provenance", {}).get("field_sources", {}).values()
                                 else "PENDING_HUMAN_REVIEW" if (extracted_data or {}).get("_provenance", {}).get("extraction_status") in {"FAILED", "MANUAL_REVIEW"}
                                 else "EXTRACTED_UNVERIFIED" if extracted_data else "PENDING_HUMAN_REVIEW"),
            extraction_status=((extracted_data or {}).get("_provenance", {}).get("extraction_status") or "COMPLETED") if extracted_data else "PENDING",
            extracted_data=extracted_data,
            extraction_provenance=(extracted_data or {}).get("_provenance"),
            status=new_status,
            version_number=new_version_number,
            linked_entity_type=old_evidence.linked_entity_type,
            linked_entity_id=old_evidence.linked_entity_id,
        )
        db.add(new_evidence)
        db.flush()

        # Create version record
        version = EvidenceVersion(
            id=f"evv_{uuid.uuid4().hex[:12]}",
            evidence_id=new_evidence_id,
            version_number=new_version_number,
            storage_key=storage_key,
            sha256=digest,
            size_bytes=len(content),
            mime_type=expected_mime,
            filename=original_name[:500],
            uploaded_by_user_id=current_user.id,
            uploader_role=current_user.role,
            replacement_reason=replacement_reason,
            status=new_status,
            extracted_data=extracted_data,
            extraction_provenance=(extracted_data or {}).get("_provenance"),
        )
        db.add(version)
        db.flush()

        _append_audit(claim, "EVIDENCE_REPLACED", current_user, db=db,
                      evidence_id=new_evidence_id,
                      role=evidence_source,
                      previous={"evidence_id": old_evidence.id, "sha256": old_evidence.sha256,
                                "version_number": old_evidence.version_number},
                      values={"logical_id": old_evidence.logical_id,
                              "new_evidence_id": new_evidence_id,
                              "version_number": new_version_number,
                              "sha256": digest,
                              "requires_review": requires_review},
                      reason=replacement_reason)

        # Reopen verification if material evidence changed during review
        if requires_review:
            claim.status = "PENDING"
            _run_verification(claim, db, current_user)
            db.flush()
            verification = db.query(VRModel).filter(VRModel.claim_id == claim.id).first()
            if verification:
                claim.status = "FLAGGED" if verification.risk_score > 0 else "PENDING"
            _append_audit(claim, "VERIFICATION_REOPENED_EVIDENCE_CHANGE", current_user, db=db,
                          evidence_id=new_evidence_id,
                          values={"trigger": "evidence_replacement",
                                  "logical_id": old_evidence.logical_id})

        db.commit()
    except Exception as exc:
        db.rollback()
        storage.delete(storage_key)
        if isinstance(exc, OperationalError):
            raise HTTPException(status_code=409, detail="Evidence changed concurrently; reload and retry") from exc
        raise

    return _build_response(_load_claim(claim_id, db, current_user))


@router.get("/{claim_id}/evidence/{evidence_id}/versions")
def get_evidence_versions(
    claim_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve the version history for an evidence document."""
    from app.models import EvidenceVersion

    _load_claim(claim_id, db, current_user)
    evidence = (
        db.query(Evidence)
        .filter(Evidence.claim_id == claim_id)
        .filter((Evidence.id == evidence_id) | (Evidence.logical_id == evidence_id))
        .first()
    )
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    # Fetch all evidence records sharing the same logical_id
    all_revisions = (
        db.query(Evidence)
        .filter(Evidence.claim_id == claim_id, Evidence.logical_id == evidence.logical_id)
        .order_by(Evidence.version_number.desc())
        .all()
    )

    return {
        "logical_id": evidence.logical_id,
        "category": evidence.category,
        "versions": [
            {
                "evidence_id": ev.id,
                "version_number": ev.version_number,
                "filename": ev.filename,
                "sha256": ev.sha256,
                "size_bytes": ev.size_bytes,
                "mime_type": ev.mime_type,
                "uploaded_at": _iso(ev.uploaded_at),
                "extraction_provenance": ev.extraction_provenance,
                "uploaded_by": {
                    "id": ev.uploader.id,
                    "name": ev.uploader.display_name,
                    "role": ev.uploader_role,
                } if ev.uploader else None,
                "status": ev.status,
                "replacement_reason": ev.replacement_reason,
                "replaced_by_id": ev.replaced_by_id,
                "linked_entity_type": ev.linked_entity_type,
                "linked_entity_id": ev.linked_entity_id,
            }
            for ev in all_revisions
        ],
    }


@router.post("/{claim_id}/evidence/{evidence_id}/archive")
def archive_evidence(
    claim_id: str,
    evidence_id: str,
    reason: str = Form(..., min_length=3, max_length=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Archive an evidence document without deleting it."""
    claim = _load_claim(claim_id, db, current_user)
    evidence = (
        db.query(Evidence)
        .filter(Evidence.id == evidence_id, Evidence.claim_id == claim_id, Evidence.status == "ACTIVE")
        .first()
    )
    if not evidence:
        raise HTTPException(status_code=404, detail="Active evidence not found")

    if current_user.role not in {PRODUCER, RECYCLER_EMPLOYEE}:
        raise HTTPException(status_code=403, detail="Cannot archive evidence with this role")
    if current_user.role == PRODUCER:
        if claim.owner_user_id != current_user.id or evidence.source != "PRODUCER":
            raise HTTPException(status_code=403, detail="Producers can only archive their own evidence")
    else:
        _assert_assigned_recycler(claim, current_user, db)
        if evidence.source != "RECYCLER":
            raise HTTPException(status_code=403, detail="Recyclers can only archive recycler evidence")
    if claim.status in {"APPROVED", "VERIFIED", "REJECTED"}:
        raise HTTPException(status_code=409, detail="Cannot archive evidence after a government decision")

    previous_status = evidence.status
    evidence.status = "ARCHIVED"
    evidence.replacement_reason = reason
    from app.models import EvidenceVersion
    active_version = db.query(EvidenceVersion).filter_by(evidence_id=evidence.id, status="ACTIVE").first()
    if active_version:
        active_version.status = "ARCHIVED"

    _append_audit(claim, "EVIDENCE_ARCHIVED", current_user, db=db,
                  evidence_id=evidence.id,
                  previous={"status": previous_status},
                  values={"status": "ARCHIVED", "logical_id": evidence.logical_id},
                  reason=reason)

    _run_verification(claim, db, current_user)
    db.commit()
    return _build_response(_load_claim(claim_id, db, current_user))


@router.get("/{claim_id}/evidence/{evidence_id}/file")
def download_evidence(
    claim_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Serve a stored evidence file after checking its claim association."""
    from app.services.storage import get_storage_backend

    _load_claim(claim_id, db, current_user)
    evidence = (
        db.query(Evidence)
        .filter(Evidence.id == evidence_id, Evidence.claim_id == claim_id)
        .first()
    )
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    storage = get_storage_backend()
    storage_key = evidence.storage_key or evidence.file_path

    # Try the new storage backend first
    try:
        content = storage.load(storage_key)
        path = storage.resolve_path(storage_key)
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), evidence.sha256):
            raise HTTPException(status_code=409, detail="Stored evidence failed its integrity check")
        media_type = evidence.mime_type or ALLOWED_EVIDENCE.get(path.suffix.lower(), ("application/octet-stream",))[0]
        return _evidence_file_response(content, media_type, evidence.filename)
    except FileNotFoundError:
        pass

    # Fallback: legacy file_path relative to the old UPLOAD_ROOT
    path = (UPLOAD_ROOT.parent / evidence.file_path).resolve()
    if not path.is_relative_to(UPLOAD_ROOT.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")
    legacy_content = path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(legacy_content).hexdigest(), evidence.sha256):
        raise HTTPException(status_code=409, detail="Stored evidence failed its integrity check")
    media_type = ALLOWED_EVIDENCE.get(path.suffix.lower(), ("application/octet-stream",))[0]
    return _evidence_file_response(legacy_content, media_type, evidence.filename)


def _evidence_file_response(content: bytes, media_type: str, filename: str) -> Response:
    safe_name = Path(filename).name
    fallback = "".join(char if 32 <= ord(char) < 127 and char not in '"\\;' else "_" for char in safe_name)
    disposition = f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(safe_name, safe='')}"
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": disposition,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })


def _validate_evidence_file(
    file: UploadFile,
    document_data: str | None,
) -> tuple[bytes, str, str, str, str, dict | None]:
    """Validate and read an evidence upload, returning (content, filename, suffix, mime, evidence_type, extracted)."""
    original_name = Path((file.filename or "").replace("\\", "/")).name
    suffix = Path(original_name).suffix.lower()
    allowed = ALLOWED_EVIDENCE.get(suffix)
    if not original_name or not allowed:
        raise HTTPException(status_code=400, detail="Only PDF, JPG, PNG, and WEBP files are allowed")
    expected_mime, signature, evidence_type = allowed
    if file.content_type != expected_mime:
        raise HTTPException(status_code=400, detail="File content type does not match its extension")

    content = file.file.read(get_settings().evidence_max_file_size + 1)
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")
    max_size = get_settings().evidence_max_file_size
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail=f"File exceeds the {max_size // (1024 * 1024)} MB limit")
    if not content.startswith(signature) or (suffix == ".webp" and content[8:12] != b"WEBP"):
        raise HTTPException(status_code=400, detail="File contents are not a valid supported document or image")

    supplied_data = None
    if isinstance(document_data, str) and document_data.strip():
        if len(document_data.encode("utf-8")) > MAX_STRUCTURED_DATA_SIZE:
            raise HTTPException(status_code=413, detail="Structured document data exceeds the 16 KB limit")
        try:
            supplied_data = json.loads(document_data)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Structured document data must be valid JSON") from exc
        if not isinstance(supplied_data, dict):
            raise HTTPException(status_code=400, detail="Structured document data must be a JSON object")
    try:
        extracted_data = get_document_extractor().extract(
            filename=original_name,
            content_type=expected_mime,
            content=content,
            supplied_data=supplied_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid structured document data: {exc}") from exc

    return content, original_name, suffix, expected_mime, evidence_type, extracted_data

