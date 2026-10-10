from contextlib import asynccontextmanager
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api import api_router
from app.database import (
    Base,
    engine,
    SessionLocal,
    run_migrations,
)
from app.auth import hash_password
from app.models import (User, RecyclerFacility, FacilityMembership,
                        GovernmentJurisdiction, GovernmentJurisdictionAssignment, Claim, AuditEvent)
from app.services.audit import calculate_event_hash, event_hash_fields, request_correlation_id

logger = logging.getLogger("chainguard")

# Import models so they register with Base.metadata before create_all
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create all DB tables on startup (dev convenience)."""
    settings = get_settings()
    if settings.environment.lower() in {"production", "prod"}:
        secret = settings.jwt_secret_key
        if len(secret) < 32 or secret.lower() in {"changeme", "secret", "development", ""}:
            raise RuntimeError("JWT_SECRET_KEY must be a unique secret of at least 32 characters in production")
        if not settings.cors_origins_list or any("localhost" in origin or "127.0.0.1" in origin for origin in settings.cors_origins_list):
            raise RuntimeError("CORS_ORIGINS must contain only the production frontend origins")
    Base.metadata.create_all(bind=engine)
    run_migrations()
    migrate_legacy_audit_history()
    seed_public_recycler_facilities()
    seed_configured_users()
    logger.info("database startup complete")
    yield


def migrate_legacy_audit_history() -> dict[str, int]:
    """Import claim JSON events once, preserving original payload and unknown metadata."""
    migrated = manual_review = 0
    valid_roles = {"PRODUCER", "RECYCLER_EMPLOYEE", "GOVERNMENT_OFFICER"}
    with SessionLocal() as db:
        claims = db.query(Claim).all()
        for claim in claims:
            if claim.legacy_audit_migrated:
                continue
            history = (claim.mass_balance_details or {}).get("audit_history") or []
            for index, payload in enumerate(history):
                source_key = f"{claim.id}:{index}"
                if db.query(AuditEvent.id).filter_by(legacy_source_key=source_key).first():
                    continue
                if not isinstance(payload, dict):
                    payload = {"legacy_value": payload}
                actor = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
                actor_id = actor.get("user_id")
                if actor_id and db.get(User, actor_id) is None:
                    actor_id = None
                role = actor.get("role") if actor.get("role") in valid_roles else None
                occurred_at = None
                timestamp = payload.get("occurred_at")
                if isinstance(timestamp, str):
                    try:
                        occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    except ValueError:
                        occurred_at = None
                if not actor_id or not role or occurred_at is None:
                    manual_review += 1
                previous = db.query(AuditEvent).filter_by(claim_id=claim.id).order_by(AuditEvent.sequence_no.desc()).first()
                event = AuditEvent(
                    id=f"evt_legacy_{uuid.uuid5(uuid.NAMESPACE_URL, source_key).hex}",
                    claim_id=claim.id,
                    sequence_no=(previous.sequence_no + 1) if previous else 1,
                    entity_type="CLAIM",
                    related_entity_id=payload.get("evidence_id") or payload.get("batch_id"),
                    actor_user_id=actor_id,
                    actor_role=role,
                    actor_display_name=actor.get("name") if isinstance(actor.get("name"), str) else None,
                    action_type=str(payload.get("action") or "LEGACY_EVENT")[:80],
                    occurred_at=occurred_at,
                    previous_values=payload.get("previous") if isinstance(payload.get("previous"), dict) else None,
                    new_values=payload.get("values") if isinstance(payload.get("values"), dict) else None,
                    reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
                    legacy_event=True,
                    legacy_source_key=source_key,
                    legacy_payload=payload,
                    previous_hash=previous.event_hash if previous else "",
                    event_hash="",
                )
                event.event_hash = calculate_event_hash(event_hash_fields(event))
                db.add(event)
                db.flush()
                migrated += 1
            claim.legacy_audit_migrated = True
        db.commit()
    if migrated or manual_review:
        logger.info("legacy audit import complete", extra={"imported": migrated, "manual_review": manual_review})
    return {"migrated": migrated, "manual_review": manual_review}


def seed_configured_users() -> None:
    """Provision optional local accounts from BOOTSTRAP_USERS_JSON environment config."""
    raw_users = get_settings().bootstrap_users_json.strip()
    if not raw_users:
        return
    users = json.loads(raw_users)
    if not isinstance(users, list):
        raise ValueError("BOOTSTRAP_USERS_JSON must be a JSON array")
    with SessionLocal() as db:
        for record in users:
            persona = record.get("persona")
            role = record.get("role") or ("GOVERNMENT_OFFICER" if persona == "GOV_OFFICIAL" else "PRODUCER")
            required = ("username", "password", "display_name", "organisation")
            if not all(record.get(key) for key in required) or role not in {"PRODUCER", "RECYCLER_EMPLOYEE", "GOVERNMENT_OFFICER", "ADMINISTRATOR"}:
                raise ValueError("Each bootstrap user needs username, password, display_name, organisation, and a valid role")
            username = record["username"].strip().lower()
            existing = db.query(User).filter_by(username=username).first()
            if existing:
                # Role changes are accepted only from server-side bootstrap config.
                if "role" in record:
                    existing.role = role
                    existing.persona = "GOV_OFFICIAL" if role == "GOVERNMENT_OFFICER" else "USER"
                    existing.department = record.get("department")
                continue
            password_hash, password_salt = hash_password(record["password"])
            db.add(User(
                id=f"usr_{uuid.uuid4().hex[:12]}",
                username=username,
                password_hash=password_hash,
                password_salt=password_salt,
                display_name=record["display_name"],
                organisation=record["organisation"],
                persona=persona or ("GOV_OFFICIAL" if role == "GOVERNMENT_OFFICER" else "USER"),
                role=role,
                department=record.get("department"),
            ))
        db.commit()


    # Registry data is provisioned only from trusted server configuration. No
    # organization-name inference or frontend role/membership assignment is used.
    with SessionLocal() as db:
        raw_facilities = get_settings().bootstrap_facilities_json.strip()
        for record in json.loads(raw_facilities) if raw_facilities else []:
            facility = db.get(RecyclerFacility, record["id"])
            if facility is None:
                facility = RecyclerFacility(id=record["id"], name=record["name"],
                    registration_number=record["registration_number"], address=record.get("address", ""),
                    authorization_status=record.get("authorization_status", "PENDING"),
                    permitted_waste_categories=record.get("permitted_waste_categories", []))
                db.add(facility)
            else:
                facility.name = record["name"]
                facility.registration_number = record["registration_number"]
                facility.address = record.get("address", "")
                facility.authorization_status = record.get("authorization_status", "PENDING")
                facility.permitted_waste_categories = record.get("permitted_waste_categories", [])
            verified_employee_ids = record.get("verified_employee_user_ids", [])
            db.query(FacilityMembership).filter(
                FacilityMembership.facility_id == facility.id,
                FacilityMembership.user_id.not_in(verified_employee_ids),
            ).delete(synchronize_session=False)
            for user_id in verified_employee_ids:
                user = db.get(User, user_id)
                if not user or user.role != "RECYCLER_EMPLOYEE":
                    raise ValueError(f"Facility {record['id']} employee must be a configured recycler employee")
                membership = db.query(FacilityMembership).filter_by(user_id=user_id, facility_id=facility.id).first()
                if membership is None:
                    db.add(FacilityMembership(user_id=user_id, facility_id=facility.id, active=True, verified=True))
                else:
                    membership.active, membership.verified = True, True
        raw_jurisdictions = get_settings().bootstrap_jurisdictions_json.strip()
        for record in json.loads(raw_jurisdictions) if raw_jurisdictions else []:
            area = db.get(GovernmentJurisdiction, record["id"])
            if area is None:
                area = GovernmentJurisdiction(id=record["id"], name=record["name"], boundary=record.get("boundary"))
                db.add(area)
            else:
                area.name, area.boundary = record["name"], record.get("boundary")
            officer_ids = set(record.get("officer_user_ids", []))
            for username in record.get("officer_usernames", []):
                officer = db.query(User).filter_by(username=username.strip().lower()).first()
                if not officer or officer.role != "GOVERNMENT_OFFICER":
                    raise ValueError(f"Jurisdiction {record['id']} assignee must be a configured government officer")
                officer_ids.add(officer.id)
            db.query(GovernmentJurisdictionAssignment).filter(
                GovernmentJurisdictionAssignment.jurisdiction_id == area.id,
                GovernmentJurisdictionAssignment.user_id.not_in(list(officer_ids)),
            ).delete(synchronize_session=False)
            for user_id in officer_ids:
                user = db.get(User, user_id)
                if not user or user.role != "GOVERNMENT_OFFICER":
                    raise ValueError(f"Jurisdiction {record['id']} assignee must be a configured government officer")
                assignment = db.query(GovernmentJurisdictionAssignment).filter_by(user_id=user_id, jurisdiction_id=area.id).first()
                if assignment is None:
                    db.add(GovernmentJurisdictionAssignment(user_id=user_id, jurisdiction_id=area.id))
        raw_memberships = get_settings().bootstrap_memberships_json.strip()
        for record in json.loads(raw_memberships) if raw_memberships else []:
            username = str(record.get("username", "")).strip().lower()
            user = db.query(User).filter_by(username=username).first()
            facility = db.get(RecyclerFacility, record.get("facility_id"))
            if not user or user.role != "RECYCLER_EMPLOYEE" or not user.is_active:
                raise ValueError("Bootstrap facility membership must reference an active recycler employee account")
            if not facility or facility.authorization_status != "AUTHORIZED":
                raise ValueError("Bootstrap facility membership must reference an authorized facility")
            membership = db.query(FacilityMembership).filter_by(
                user_id=user.id, facility_id=facility.id
            ).first()
            if membership is None:
                db.add(FacilityMembership(
                    user_id=user.id, facility_id=facility.id, active=True, verified=True
                ))
            else:
                membership.active, membership.verified = True, True
        db.commit()


def seed_public_recycler_facilities() -> None:
    """Idempotently add the reviewed public recycler starter dataset to local DBs.

    Existing facility rows are left untouched so administrative status changes remain
    authoritative after initial provisioning.
    """
    source = Path(__file__).parent / "data" / "recycler_facility_seed.json"
    facilities = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(facilities, list):
        raise ValueError("Recycler facility seed must be a JSON array")
    with SessionLocal() as db:
        for record in facilities:
            if db.get(RecyclerFacility, record["id"]) is not None:
                continue
            duplicate_registration = db.query(RecyclerFacility).filter_by(
                registration_number=record["registration_number"]
            ).first()
            if duplicate_registration:
                continue
            db.add(RecyclerFacility(
                id=record["id"],
                name=record["name"],
                registration_number=record["registration_number"],
                address=record["address"],
                authorization_status=record["authorization_status"],
                permitted_waste_categories=record["permitted_waste_categories"],
            ))
        db.commit()


app = FastAPI(
    title="E-Waste ChainGuard API",
    description="Computational proof-of-recycling verification infrastructure",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def handle_http_error(request: Request, exc: HTTPException):
    """Keep the existing `detail` contract and attach a supportable request ID."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": request_correlation_id.get()},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "request_id": request_correlation_id.get()},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    correlation_id = request_correlation_id.get()
    logger.exception("unhandled application error", extra={
        "request_id": correlation_id,
        "method": request.method,
        "path": request.url.path,
    })
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred.", "request_id": correlation_id},
    )


class RequestBodyLimitMiddleware:
    """Bound request bodies, including chunked uploads without Content-Length."""
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                response_body = b'{"detail":"Request body is too large"}'
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(response_body)).encode())]})
                await send({"type": "http.response.body", "body": response_body})
                return
            more_body = message.get("more_body", False)

        delivered = False
        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.app(scope, replay_receive, send)


app.add_middleware(RequestBodyLimitMiddleware, max_bytes=get_settings().max_request_body_bytes)


@app.middleware("http")
async def add_request_correlation_id(request, call_next):
    correlation_id = uuid.uuid4().hex
    token = request_correlation_id.set(correlation_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if get_settings().environment.lower() in {"production", "prod"}:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        logger.info("request completed", extra={
            "request_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        })
        return response
    except Exception:
        logger.exception("request failed", extra={
            "request_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        })
        raise
    finally:
        request_correlation_id.reset(token)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {
        "service": "E-Waste ChainGuard",
        "status": "operational",
        "docs": "/api/docs",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
