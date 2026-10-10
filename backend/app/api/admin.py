"""Controlled administrative provisioning and legacy mapping review."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import ADMINISTRATOR, require_administrator
from app.database import get_db
from app.models import (AdminAuditEvent, AuditEvent, Claim, FacilityMembership,
                        GovernmentJurisdiction, GovernmentJurisdictionAssignment,
                        RecyclerFacility, User)

router = APIRouter(prefix="/admin", tags=["Administration"])


def _verify_admin_chain(events) -> bool:
    previous_hash = ""
    for sequence, event in enumerate(events, start=1):
        fields = {
            "id": event.id, "sequence_no": event.sequence_no, "actor_user_id": event.actor_user_id,
            "actor_role": event.actor_role, "action_type": event.action_type,
            "entity_type": event.entity_type, "entity_id": event.entity_id,
            "occurred_at": event.occurred_at, "reason": event.reason,
            "previous_values": event.previous_values, "new_values": event.new_values,
            "previous_hash": event.previous_hash,
        }
        expected = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        if event.sequence_no != sequence or event.previous_hash != previous_hash or event.event_hash != expected:
            return False
        previous_hash = event.event_hash
    return True


def _validated_reason(value: str) -> str:
    value = value.strip()
    if len(value) < 8:
        raise ValueError("Reason must contain at least eight non-whitespace characters")
    return value


class FacilityBody(BaseModel):
    id: str | None = Field(default=None, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    registration_number: str = Field(min_length=1, max_length=100)
    address: str = Field(default="", max_length=500)
    authorization_status: str = "PENDING"
    permitted_waste_categories: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_present(cls, value):
        return _validated_reason(value)

    @field_validator("authorization_status")
    @classmethod
    def valid_status(cls, value):
        value = value.upper()
        if value not in {"PENDING", "AUTHORIZED", "SUSPENDED", "DEACTIVATED"}:
            raise ValueError("Invalid facility status")
        return value

    @field_validator("permitted_waste_categories")
    @classmethod
    def clean_categories(cls, values):
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))


class MembershipBody(BaseModel):
    active: bool = True
    verified: bool = False
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_present(cls, value):
        return _validated_reason(value)


class JurisdictionBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    boundary: list[list[float]] | None = None
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_present(cls, value):
        return _validated_reason(value)

    @field_validator("boundary")
    @classmethod
    def valid_boundary(cls, value):
        if value is None:
            return value
        if len(value) < 3 or any(len(point) != 2 for point in value):
            raise ValueError("Boundary needs at least three [longitude, latitude] points")
        if any(not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90 for point in value):
            raise ValueError("Boundary coordinates are out of range")
        return value


class ReasonBody(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_present(cls, value):
        return _validated_reason(value)


class ResolveClaimBody(BaseModel):
    recycler_facility_id: str | None = None
    jurisdiction_id: str | None = None
    confirm: bool = False
    reason: str = Field(min_length=8, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_present(cls, value):
        return _validated_reason(value)


def _snapshot(model, fields):
    return {field: getattr(model, field) for field in fields}


def _log(db: Session, actor: User, action: str, entity_type: str, entity_id: str,
         reason: str, before: dict | None, after: dict | None) -> AdminAuditEvent:
    previous = db.query(AdminAuditEvent).order_by(AdminAuditEvent.sequence_no.desc()).first()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    record = {
        "id": f"adm_{uuid.uuid4().hex}",
        "sequence_no": previous.sequence_no + 1 if previous else 1,
        "actor_user_id": actor.id,
        "actor_role": ADMINISTRATOR,
        "action_type": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "occurred_at": now,
        "reason": reason.strip(),
        "previous_values": before,
        "new_values": after,
        "previous_hash": previous.event_hash if previous else "",
    }
    record["event_hash"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    event = AdminAuditEvent(**record)
    db.add(event)
    db.flush()
    return event


@router.get("/facilities")
def list_facilities(db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    return [{"id": f.id, "name": f.name, "registration_number": f.registration_number,
             "address": f.address, "authorization_status": f.authorization_status,
             "permitted_waste_categories": f.permitted_waste_categories or [],
             "memberships": [{"user_id": m.user_id, "display_name": m.user.display_name,
                              "active": m.active, "verified": m.verified}
                             for m in db.query(FacilityMembership).filter_by(facility_id=f.id).all()]}
            for f in db.query(RecyclerFacility).order_by(RecyclerFacility.name).all()]


@router.post("/facilities", status_code=201)
def save_facility(body: FacilityBody, db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    facility_id = body.id or f"fac_{uuid.uuid4().hex[:12]}"
    facility = db.get(RecyclerFacility, facility_id)
    if facility is None and body.id is None:
        facility = db.query(RecyclerFacility).filter_by(registration_number=body.registration_number.strip()).first()
        if facility is not None:
            facility_id = facility.id
    created = facility is None
    if created:
        facility = RecyclerFacility(id=facility_id, name=body.name.strip(),
            registration_number=body.registration_number.strip(), address=body.address.strip(),
            authorization_status=body.authorization_status,
            permitted_waste_categories=body.permitted_waste_categories)
        db.add(facility)
        before = None
    else:
        before = _snapshot(facility, ("name", "registration_number", "address", "authorization_status", "permitted_waste_categories"))
        facility.name, facility.registration_number = body.name.strip(), body.registration_number.strip()
        facility.address, facility.authorization_status = body.address.strip(), body.authorization_status
        facility.permitted_waste_categories = body.permitted_waste_categories
        after = _snapshot(facility, ("name", "registration_number", "address", "authorization_status", "permitted_waste_categories"))
        if before == after:
            return {"id": facility.id, "name": facility.name, "authorization_status": facility.authorization_status}
    if created:
        after = _snapshot(facility, ("name", "registration_number", "address", "authorization_status", "permitted_waste_categories"))
    try:
        _log(db, actor, "FACILITY_REGISTERED" if created else "FACILITY_UPDATED", "FACILITY", facility_id,
             body.reason, before, after)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Facility registration number must be unique")
    return {"id": facility.id, "name": facility.name, "authorization_status": facility.authorization_status}


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    return [{"id": u.id, "username": u.username, "display_name": u.display_name,
             "organisation": u.organisation, "role": u.role, "is_active": u.is_active,
             "facility_memberships": db.query(FacilityMembership).filter_by(user_id=u.id, active=True, verified=True).count(),
             "jurisdiction_assignments": db.query(GovernmentJurisdictionAssignment).filter_by(user_id=u.id).count()}
            for u in db.query(User).order_by(User.username).all()]


@router.post("/accounts/{user_id}/status")
def set_account_status(user_id: str, body: ReasonBody, active: bool = Query(...),
                       db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.id == actor.id and not active:
        raise HTTPException(status_code=409, detail="Administrators cannot deactivate their own account")
    before = {"is_active": user.is_active}
    if user.is_active == active:
        return {"id": user.id, "is_active": user.is_active}
    user.is_active = active
    _log(db, actor, "ACCOUNT_ACTIVATED" if active else "ACCOUNT_DEACTIVATED", "USER", user.id,
         body.reason, before, {"is_active": active})
    db.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.post("/facilities/{facility_id}/members/{user_id}")
def set_membership(facility_id: str, user_id: str, body: MembershipBody,
                   db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    facility, user = db.get(RecyclerFacility, facility_id), db.get(User, user_id)
    if facility is None or user is None:
        raise HTTPException(status_code=404, detail="Facility or employee not found")
    if user.role != "RECYCLER_EMPLOYEE":
        raise HTTPException(status_code=422, detail="Only recycler employee accounts can be assigned to a facility")
    membership = db.query(FacilityMembership).filter_by(facility_id=facility_id, user_id=user_id).first()
    before = {"active": membership.active, "verified": membership.verified} if membership else None
    if membership is None:
        membership = FacilityMembership(facility_id=facility_id, user_id=user_id,
                                        active=body.active, verified=body.verified)
        db.add(membership)
    else:
        if before == {"active": body.active, "verified": body.verified}:
            return {"facility_id": facility_id, "user_id": user_id, "active": membership.active, "verified": membership.verified}
        membership.active, membership.verified = body.active, body.verified
    _log(db, actor, "MEMBERSHIP_UPDATED", "FACILITY_MEMBERSHIP", f"{facility_id}:{user_id}",
         body.reason, before, {"active": body.active, "verified": body.verified})
    db.commit()
    return {"facility_id": facility_id, "user_id": user_id, "active": membership.active, "verified": membership.verified}


@router.delete("/facilities/{facility_id}/members/{user_id}")
def revoke_membership(facility_id: str, user_id: str, body: ReasonBody,
                      db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    membership = db.query(FacilityMembership).filter_by(facility_id=facility_id, user_id=user_id).first()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    before = {"active": membership.active, "verified": membership.verified}
    membership.active = False
    _log(db, actor, "MEMBERSHIP_REVOKED", "FACILITY_MEMBERSHIP", f"{facility_id}:{user_id}",
         body.reason, before, {"active": False, "verified": membership.verified})
    db.commit()
    return {"facility_id": facility_id, "user_id": user_id, "active": False}


@router.get("/jurisdictions")
def list_jurisdictions(db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    return [{"id": j.id, "name": j.name, "boundary": j.boundary,
             "officers": [{"user_id": a.user_id, "display_name": a.user.display_name}
                          for a in db.query(GovernmentJurisdictionAssignment).filter_by(jurisdiction_id=j.id).all()]}
            for j in db.query(GovernmentJurisdiction).order_by(GovernmentJurisdiction.name).all()]


@router.post("/jurisdictions/{jurisdiction_id}", status_code=200)
def save_jurisdiction(jurisdiction_id: str, body: JurisdictionBody,
                      db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    area = db.get(GovernmentJurisdiction, jurisdiction_id)
    before = _snapshot(area, ("name", "boundary")) if area else None
    if area is None:
        area = GovernmentJurisdiction(id=jurisdiction_id, name=body.name.strip(), boundary=body.boundary)
        db.add(area)
    else:
        if before == {"name": body.name.strip(), "boundary": body.boundary}:
            return {"id": area.id, "name": area.name, "boundary": area.boundary}
        area.name, area.boundary = body.name.strip(), body.boundary
    _log(db, actor, "JURISDICTION_CREATED" if before is None else "JURISDICTION_UPDATED",
         "JURISDICTION", area.id, body.reason, before, {"name": area.name, "boundary": area.boundary})
    db.commit()
    return {"id": area.id, "name": area.name, "boundary": area.boundary}


@router.post("/jurisdictions/{jurisdiction_id}/officers/{user_id}")
def assign_officer(jurisdiction_id: str, user_id: str, body: ReasonBody,
                   db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    area, user = db.get(GovernmentJurisdiction, jurisdiction_id), db.get(User, user_id)
    if area is None or user is None:
        raise HTTPException(status_code=404, detail="Jurisdiction or account not found")
    if user.role != "GOVERNMENT_OFFICER":
        raise HTTPException(status_code=422, detail="Only government officer accounts can be assigned")
    assignment = db.query(GovernmentJurisdictionAssignment).filter_by(user_id=user_id, jurisdiction_id=jurisdiction_id).first()
    if assignment:
        return {"jurisdiction_id": jurisdiction_id, "user_id": user_id, "assigned": True}
    db.add(GovernmentJurisdictionAssignment(user_id=user_id, jurisdiction_id=jurisdiction_id))
    _log(db, actor, "OFFICER_ASSIGNED", "JURISDICTION_ASSIGNMENT", f"{jurisdiction_id}:{user_id}",
         body.reason, None, {"jurisdiction_id": jurisdiction_id, "user_id": user_id})
    db.commit()
    return {"jurisdiction_id": jurisdiction_id, "user_id": user_id, "assigned": True}


@router.delete("/jurisdictions/{jurisdiction_id}/officers/{user_id}")
def revoke_officer(jurisdiction_id: str, user_id: str, body: ReasonBody,
                   db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    assignment = db.query(GovernmentJurisdictionAssignment).filter_by(user_id=user_id, jurisdiction_id=jurisdiction_id).first()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(assignment)
    _log(db, actor, "OFFICER_ASSIGNMENT_REVOKED", "JURISDICTION_ASSIGNMENT", f"{jurisdiction_id}:{user_id}",
         body.reason, {"jurisdiction_id": jurisdiction_id, "user_id": user_id}, None)
    db.commit()
    return {"jurisdiction_id": jurisdiction_id, "user_id": user_id, "assigned": False}


@router.get("/legacy")
def unresolved_records(db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    claims = db.query(Claim).all()
    unresolved_claims = []
    for claim in claims:
        facility = db.get(RecyclerFacility, claim.recycler_facility_id) if claim.recycler_facility_id else None
        jurisdiction = db.get(GovernmentJurisdiction, claim.jurisdiction_id) if claim.jurisdiction_id else None
        reviewed_mapping = db.query(AuditEvent).filter_by(
            claim_id=claim.id, action_type="ADMIN_LEGACY_MAPPING_RESOLVED").order_by(AuditEvent.sequence_no.desc()).first()
        explicitly_reviewed_facility = bool(reviewed_mapping and reviewed_mapping.new_values
            and reviewed_mapping.new_values.get("recycler_facility_id") == claim.recycler_facility_id
            and facility is not None
            and reviewed_mapping.new_values.get("resolved_facility_name") == facility.name
            and reviewed_mapping.new_values.get("resolved_facility_registration_number") == facility.registration_number)
        missing = []
        if (facility is None or facility.authorization_status != "AUTHORIZED"
                or claim.waste_category not in (facility.permitted_waste_categories or [])):
            missing.append("facility")
        elif ((claim.recycler_name != facility.name or claim.recycler_registration_number != facility.registration_number)
              and not explicitly_reviewed_facility):
            missing.append("facility")
        if jurisdiction is None:
            missing.append("jurisdiction")
        if missing:
            unresolved_claims.append({"id": claim.id, "reference_number": claim.reference_number,
                "recycler_name": claim.recycler_name, "recycler_registration_number": claim.recycler_registration_number,
                "original_facility_id": claim.recycler_facility_id, "original_jurisdiction_id": claim.jurisdiction_id,
                "unresolved": missing})
    recycler_accounts = [{"id": u.id, "username": u.username, "display_name": u.display_name,
        "organisation": u.organisation}
        for u in db.query(User).filter_by(role="RECYCLER_EMPLOYEE", is_active=True).all()
        if db.query(FacilityMembership).filter_by(user_id=u.id, active=True, verified=True).count() == 0]
    government_accounts = [{"id": u.id, "username": u.username, "display_name": u.display_name,
        "organisation": u.organisation}
        for u in db.query(User).filter_by(role="GOVERNMENT_OFFICER", is_active=True).all()
        if db.query(GovernmentJurisdictionAssignment).filter_by(user_id=u.id).count() == 0]
    return {"claims": unresolved_claims, "recycler_accounts": recycler_accounts,
            "government_accounts": government_accounts}


@router.post("/legacy/claims/{claim_id}/resolve")
def resolve_claim(claim_id: str, body: ResolveClaimBody,
                  db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Explicit mapping confirmation is required")
    if body.recycler_facility_id is None and body.jurisdiction_id is None:
        raise HTTPException(status_code=422, detail="Select at least one mapping to resolve")
    before = {"recycler_facility_id": claim.recycler_facility_id, "jurisdiction_id": claim.jurisdiction_id,
              "recycler_name": claim.recycler_name, "recycler_registration_number": claim.recycler_registration_number}
    if body.recycler_facility_id is not None:
        facility = db.get(RecyclerFacility, body.recycler_facility_id)
        if facility is None or facility.authorization_status != "AUTHORIZED":
            raise HTTPException(status_code=422, detail="Choose an existing authorized facility")
        if claim.waste_category not in (facility.permitted_waste_categories or []):
            raise HTTPException(status_code=422, detail="Facility is not permitted for this claim category")
        claim.recycler_facility_id = facility.id
    if body.jurisdiction_id is not None:
        if db.get(GovernmentJurisdiction, body.jurisdiction_id) is None:
            raise HTTPException(status_code=422, detail="Choose an existing jurisdiction")
        claim.jurisdiction_id = body.jurisdiction_id
    after = {"recycler_facility_id": claim.recycler_facility_id, "jurisdiction_id": claim.jurisdiction_id,
             "recycler_name": claim.recycler_name, "recycler_registration_number": claim.recycler_registration_number,
             "resolved_facility_name": facility.name if body.recycler_facility_id is not None else None,
             "resolved_facility_registration_number": facility.registration_number if body.recycler_facility_id is not None else None}
    previous_confirmation = db.query(AuditEvent).filter_by(
        claim_id=claim.id, action_type="ADMIN_LEGACY_MAPPING_RESOLVED").order_by(AuditEvent.sequence_no.desc()).first()
    confirmed_facility = body.recycler_facility_id is None or bool(previous_confirmation and previous_confirmation.new_values
        and facility is not None
        and previous_confirmation.new_values.get("resolved_facility_name") == facility.name
        and previous_confirmation.new_values.get("resolved_facility_registration_number") == facility.registration_number)
    already_confirmed = bool(confirmed_facility and previous_confirmation and previous_confirmation.new_values
        and previous_confirmation.new_values.get("recycler_facility_id") == claim.recycler_facility_id
        and previous_confirmation.new_values.get("jurisdiction_id") == claim.jurisdiction_id)
    if (before["recycler_facility_id"] == claim.recycler_facility_id
            and before["jurisdiction_id"] == claim.jurisdiction_id and already_confirmed):
        return {"id": claim.id, "recycler_facility_id": claim.recycler_facility_id,
                "jurisdiction_id": claim.jurisdiction_id, "confirmed": True}
    _log(db, actor, "LEGACY_CLAIM_MAPPING_RESOLVED", "CLAIM", claim.id, body.reason, before, after)
    from app.api.claims import _append_audit
    _append_audit(claim, "ADMIN_LEGACY_MAPPING_RESOLVED", actor, db=db,
                  previous=before, values=after, reason=body.reason)
    db.commit()
    return {"id": claim.id, "recycler_facility_id": claim.recycler_facility_id,
            "jurisdiction_id": claim.jurisdiction_id, "confirmed": True}


@router.get("/activity")
def administrative_activity(limit: int = Query(default=100, ge=1, le=500),
                             db: Session = Depends(get_db), actor: User = Depends(require_administrator)):
    all_events = db.query(AdminAuditEvent).order_by(AdminAuditEvent.sequence_no.asc()).all()
    chain_valid = _verify_admin_chain(all_events)
    events = db.query(AdminAuditEvent).order_by(AdminAuditEvent.sequence_no.desc()).limit(limit).all()
    return [{"id": e.id, "sequence_no": e.sequence_no, "actor_user_id": e.actor_user_id,
             "actor_display_name": e.actor.display_name, "actor_role": e.actor_role,
             "action_type": e.action_type, "entity_type": e.entity_type, "entity_id": e.entity_id,
             "occurred_at": e.occurred_at.isoformat(), "reason": e.reason,
             "previous_values": e.previous_values, "new_values": e.new_values,
             "previous_hash": e.previous_hash, "event_hash": e.event_hash}
            for e in events]


@router.get("/activity/verify")
def verify_administrative_activity(db: Session = Depends(get_db),
                                   actor: User = Depends(require_administrator)):
    events = db.query(AdminAuditEvent).order_by(AdminAuditEvent.sequence_no.asc()).all()
    return {"chain_valid": _verify_admin_chain(events), "event_count": len(events)}
