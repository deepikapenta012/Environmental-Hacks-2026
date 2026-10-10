import hashlib
import io

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile

from app.api import claims as claims_api
from app.database import Base
from app.main import migrate_legacy_audit_history
from app.models import (AuditEvent, Claim, Evidence, FacilityMembership, RecyclerFacility,
                        GovernmentJurisdiction, GovernmentJurisdictionAssignment,
                        User, VerificationResult)
from app.auth import hash_password
from app.schemas import (
    ApproveBody,
    AuditNoteBody,
    ClaimCreate,
    ProcessingSubmission,
    ReceiptConfirmation,
    RejectBody,
    RequestClarificationBody,
    FlagDismissBody,
)
from app.verification import (
    Flag,
    check_mass_balance,
    check_transport_speed,
    compute_risk_score,
    score_flags,
)
from app.services.storage import LocalStorageBackend, get_storage_backend, set_storage_backend


@pytest.fixture(autouse=True)
def isolated_evidence_storage(tmp_path):
    set_storage_backend(LocalStorageBackend(tmp_path / "evidence_store"))
    yield
    set_storage_backend(None)


@pytest.fixture
def db_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    password_hash, password_salt = hash_password("test-password")
    with factory() as db:
        for user_id, username, persona, organisation, role in (
            ("user-1", "producer", "USER", "Producer Ltd", "PRODUCER"),
            ("user-2", "other-producer", "USER", "Other Producer Ltd", "PRODUCER"),
            ("recycler-1", "recycler", "USER", "Recycler Ltd", "RECYCLER_EMPLOYEE"),
            ("gov-1", "official", "GOV_OFFICIAL", "Government", "GOVERNMENT_OFFICER"),
        ):
            db.add(User(
                id=user_id, username=username, password_hash=password_hash,
                password_salt=password_salt, display_name=username,
                organisation=organisation, persona=persona,
                role=role,
            ))
        db.add(RecyclerFacility(id="facility-1", name="Recycler Ltd", registration_number="RC-123",
                                address="Test", authorization_status="AUTHORIZED",
                                permitted_waste_categories=["WEEE Category 1"]))
        db.add(FacilityMembership(user_id="recycler-1", facility_id="facility-1", active=True, verified=True))
        db.add(GovernmentJurisdiction(id="jurisdiction-1", name="Test Area",
                                      boundary=[[76.0, 12.0], [79.0, 12.0], [79.0, 14.0], [76.0, 14.0]]))
        db.add(GovernmentJurisdictionAssignment(user_id="gov-1", jurisdiction_id="jurisdiction-1"))
        db.commit()
    yield factory
    engine.dispose()


def claim_body(**overrides):
    values = {
        "producer_name": "Producer Ltd",
        "producer_registration_number": "PR-123",
        "recycler_name": "Recycler Ltd",
        "recycler_registration_number": "RC-123",
        "recycler_facility_id": "facility-1",
        "waste_category": "WEEE Category 1",
        "waste_subcategories": [],
        "declared_weight_kg": 100,
        "collection_date": "2026-10-08",
        "vehicle_registration": "KA-01-AA-1000",
        "driver_name": "Test Driver",
        "origin_lat": 12.9,
        "origin_lng": 77.5,
        "destination_lat": 13.0,
        "destination_lng": 77.6,
        "origin_address": "Origin",
        "destination_address": "Destination",
        "departed_at": "2026-10-08T09:00:00",
        "arrived_at": "2026-10-08T10:00:00",
        "notes": None,
    }
    values.update(overrides)
    return ClaimCreate(**values)


def create_claim(db, **overrides):
    return claims_api.create_claim(
        claim_body(**overrides), db, db.get(User, "user-1")
    )


def confirm_and_process(db, claim_id, *, received_weight=100, output=80, recovered=60, residual=20):
    recycler = db.get(User, "recycler-1")
    claims_api.confirm_receipt(
        claim_id,
        ReceiptConfirmation(
            received_weight_kg=received_weight,
            received_at="2026-10-08T11:00:00Z",
        ),
        db,
        recycler,
    )
    return claims_api.submit_processing(
        claim_id,
        ProcessingSubmission(
            processed_output_kg=output,
            recovered_materials_total_kg=recovered,
            residual_waste_kg=residual,
            processing_date="2026-10-09",
        ),
        db,
        recycler,
    )


def create_complete_claim(db, **overrides):
    created = create_claim(db, **overrides)
    return confirm_and_process(db, created["id"])


def upload_pdf(claim_id, filename, content, db, user_id="user-1"):
    upload = UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers=Headers({"content-type": "application/pdf"}),
    )
    return claims_api.upload_evidence(claim_id, upload, db, db.get(User, user_id))


def test_claim_creation_persists_to_database(db_factory):
    with db_factory() as db:
        response = create_claim(db)
        claim_id = response["id"]
        assert response["status"] == "AWAITING_RECYCLER_CONFIRMATION"
        assert response["mass_balance"]["declared_input_kg"] == 100
        assert response["mass_balance"]["received_input_kg"] is None
        assert response["verification_result"] is None

    with db_factory() as db:
        saved = db.get(Claim, claim_id)
        assert saved is not None
        assert saved.reference_number.startswith("EWC-")
        assert saved.producer_name == "Producer Ltd"
        events = db.query(AuditEvent).filter_by(claim_id=claim_id).all()
        assert len(events) == 1
        assert events[0].action_type == "CLAIM_SUBMITTED"
        assert events[0].actor_role == "PRODUCER"
        assert events[0].event_hash


def test_audit_events_reject_orm_mutation(db_factory):
    with db_factory() as db:
        claim = create_claim(db)
        event = db.query(AuditEvent).filter_by(claim_id=claim["id"]).one()
        event.reason = "tampered"
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()
        event = db.query(AuditEvent).filter_by(claim_id=claim["id"]).one()
        db.delete(event)
        with pytest.raises(ValueError, match="append-only"):
            db.flush()


def test_claim_update_and_audit_event_rollback_together(db_factory):
    with db_factory() as db:
        created = create_claim(db)
        claim = db.get(Claim, created["id"])
        before_count = db.query(AuditEvent).filter_by(claim_id=claim.id).count()
        claim.notes = "temporary update"
        claims_api._append_audit(claim, "TEST_ATOMIC_CHANGE", db.get(User, "user-1"), db=db,
                                 previous={"notes": None}, values={"notes": "temporary update"})
        db.rollback()
        saved = db.get(Claim, claim.id)
        assert saved.notes is None
        assert db.query(AuditEvent).filter_by(claim_id=claim.id).count() == before_count


def test_legacy_audit_import_preserves_unknown_fields_and_is_idempotent(db_factory, monkeypatch):
    import app.main as main_module
    factory = db_factory
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    with factory() as db:
        created = create_claim(db)
        claim = db.get(Claim, created["id"])
        payload = {"action": "OLD_EVENT", "actor": {"name": "Unverified Name", "role": "RECYCLER"}}
        claim.mass_balance_details = {**claim.mass_balance_details, "audit_history": [payload]}
        claim.legacy_audit_migrated = False
        db.commit()
    first = migrate_legacy_audit_history()
    second = migrate_legacy_audit_history()
    assert first["migrated"] == 1
    assert second["migrated"] == 0
    with factory() as db:
        event = db.query(AuditEvent).filter_by(legacy_event=True).one()
        assert event.actor_user_id is None
        assert event.actor_role is None
        assert event.occurred_at is None
        assert event.legacy_payload == payload


def test_claim_retrieval_returns_claim_and_verification(db_factory):
    with db_factory() as db:
        created = create_complete_claim(db)
        retrieved = claims_api.get_claim(created["id"], db, db.get(User, "user-1"))

    assert retrieved["id"] == created["id"]
    assert retrieved["reference_number"] == created["reference_number"]
    assert retrieved["verification_result"]["claim_id"] == created["id"]
    assert retrieved["verification_result"]["risk_score"] == 0
    assert not any("MISSING_EVIDENCE" in flag["code"] for flag in retrieved["verification_result"]["flags"])


def test_mass_balance_rules_flag_output_excess_and_shortfall():
    flags = check_mass_balance(100, 70, 110, ["ev-a"])

    assert {flag.code for flag in flags} == {
        "MB_VARIANCE_CRITICAL",
        "MB_TRANSPORT_SHORTFALL",
        "MB_MISSING_MEASUREMENTS",
    }
    assert all(flag.layer == "MASS_BALANCE" for flag in flags)
    assert all(flag.evidence_ids == ["ev-a"] for flag in flags)


def test_transport_rule_flags_impossible_gps_speed():
    flags = check_transport_speed(
        origin_lat=0,
        origin_lng=0,
        dest_lat=30,
        dest_lng=30,
        departed_iso="2026-10-08T09:00:00",
        arrived_iso="2026-10-08T10:00:00",
        vehicle_reg="KA-01-AA-1000",
        evidence_ids=["ev-route"],
    )

    assert len(flags) == 1
    assert flags[0].code == "GEO_IMPOSSIBLE_TRANSIT"
    assert flags[0].evidence_ids == ["ev-route"]


def test_risk_score_sums_and_classifies_rule_contributions():
    flags = [
        Flag("MB", "MASS_BALANCE", "WARNING", "mass", score_delta=18),
        Flag("GEO", "GEOSPATIAL", "CRITICAL", "speed", score_delta=22),
        Flag("DUP", "DUPLICATE", "CRITICAL", "duplicate", score_delta=28),
    ]

    assert compute_risk_score(flags) == (68, "HIGH")
    assert compute_risk_score(flags * 5) == (100, "CRITICAL")


def test_configured_score_groups_cap_correlated_mass_balance_findings():
    flags = [
        Flag("MB1", "MASS_BALANCE", "CRITICAL", "output exceeds receipt", rule_reference="MB-001", score_delta=18),
        Flag("MB2", "MASS_BALANCE", "WARNING", "receipt differs from declaration", rule_reference="MB-002", score_delta=18),
    ]
    score, band, per_flag = score_flags(flags)
    assert (score, band, per_flag) == (30, "MEDIUM", [18, 12])
    assert score_flags(flags, weights={"MB-001": 5}, group_caps={"MASS_BALANCE": 20}) == (20, "LOW", [5, 15])


def test_missing_measurements_are_informational_and_do_not_add_risk():
    flags = check_mass_balance(100, None, None, [])
    missing = next(flag for flag in flags if flag.code == "MB_MISSING_MEASUREMENTS")
    assert missing.severity == "INFO"
    assert compute_risk_score(flags) == (0, "LOW")


def test_verification_result_is_persisted(db_factory):
    with db_factory() as db:
        created = create_claim(
            db,
            destination_lat=30,
            destination_lng=30,
        )
        complete = confirm_and_process(db, created["id"], received_weight=70, output=120, recovered=80, residual=20)
        claim_id = complete["id"]

    with db_factory() as db:
        result = db.query(VerificationResult).filter_by(claim_id=claim_id).one()
        codes = {flag["code"] for flag in result.flags}
        assert {"MB_VARIANCE_CRITICAL", "MB_TRANSPORT_SHORTFALL", "GEO_IMPOSSIBLE_TRANSIT"} <= codes
        assert result.risk_score > 0
        assert result.risk_level in {"MEDIUM", "HIGH", "CRITICAL"}


def test_approve_and_reject_workflows(db_factory):
    with db_factory() as db:
        claim_to_approve = create_complete_claim(db)
        claim_to_reject = create_complete_claim(db)

        approved = claims_api.approve_claim(
            claim_to_approve["id"], ApproveBody(official_name="Auditor"), db,
            db.get(User, "gov-1"),
        )
        rejected = claims_api.reject_claim(
            claim_to_reject["id"],
            RejectBody(official_name="Auditor", reason="Evidence is incomplete"),
            db, db.get(User, "gov-1"),
        )

    assert approved["status"] == "APPROVED"
    assert "Approved by official" in approved["notes"]
    assert rejected["status"] == "REJECTED"
    assert "Evidence is incomplete" in rejected["notes"]


def test_evidence_upload_persists_file_metadata_and_hash(db_factory):
    content = b"%PDF-1.4\nproof\n"
    with db_factory() as db:
        claim = create_claim(db)
        response = upload_pdf(claim["id"], "receipt.pdf", content, db)
        saved = response["evidence"][0]
        evidence_id = saved["id"]

        assert saved["sha256"] == hashlib.sha256(content).hexdigest()
        assert saved["source"] == "PRODUCER"
        assert saved["category"] == "OTHER_SUPPORTING"
        assert saved["uploaded_by"]["id"] == "user-1"
        assert saved["verification_status"] == "PENDING_HUMAN_REVIEW"
        assert saved["size_bytes"] == len(content)
        stored_path = get_storage_backend().resolve_path(saved["s3_key"])
        assert stored_path.read_bytes() == content

    with db_factory() as db:
        persisted = db.get(Evidence, evidence_id)
        assert persisted is not None
        assert persisted.claim_id == claim["id"]
        assert persisted.sha256 == hashlib.sha256(content).hexdigest()
        assert persisted.uploaded_by_user_id == "user-1"


def test_identical_evidence_upload_is_flagged_with_ids_and_risk(db_factory):
    content = b"%PDF-1.4\nidentical evidence\n"
    with db_factory() as db:
        claim = create_claim(db)
        first = upload_pdf(claim["id"], "first.pdf", content, db)
        assert first["verification_result"] is None
        confirm_and_process(db, claim["id"])
        complete = claims_api.get_claim(claim["id"], db, db.get(User, "user-1"))
        assert not any(flag["code"] == "DUPLICATE_SHA256" for flag in complete["verification_result"]["flags"])

        second = upload_pdf(claim["id"], "second.pdf", content, db, "recycler-1")
        duplicate_flags = [
            flag for flag in second["verification_result"]["flags"]
            if flag["code"] == "DUPLICATE_SHA256"
        ]

        assert len(duplicate_flags) == 1
        duplicate_file = next(item for item in second["evidence"] if item["filename"] == "second.pdf")
        assert duplicate_file["verification_status"] == "DISCREPANCY_DETECTED"
        assert set(duplicate_flags[0]["evidence_ids"]) == {item["id"] for item in second["evidence"]}
        assert second["verification_result"]["explainability"]["duplicate_score"] == 15
        # Global byte equality and within-claim duplicate indicators are capped
        # together by the duplicate score group.
        assert second["verification_result"]["risk_score"] == complete["verification_result"]["risk_score"] + 18

        persisted = db.query(VerificationResult).filter_by(claim_id=claim["id"]).one()
        assert persisted.explainability["duplicate_score"] == 15


def test_recycler_batches_audit_corrections_and_facility_access(db_factory):
    with pytest.raises(ValidationError):
        claim_body(collection_date="not-a-date")
    with db_factory() as db:
        coworker_hash, coworker_salt = hash_password("test-password")
        coworker = User(
            id="recycler-coworker", username="recycler-coworker",
            password_hash=coworker_hash, password_salt=coworker_salt,
            display_name="Recycler Coworker", organisation="Recycler Ltd", persona="USER",
            role="RECYCLER_EMPLOYEE",
        )
        other_hash, other_salt = hash_password("test-password")
        other = User(
            id="recycler-other", username="recycler-other",
            password_hash=other_hash, password_salt=other_salt,
            display_name="Other Recycler", organisation="Different Facility", persona="USER",
            role="RECYCLER_EMPLOYEE",
        )
        db.add_all([coworker, other])
        db.add(FacilityMembership(user_id="recycler-coworker", facility_id="facility-1", active=True, verified=True))
        db.add(RecyclerFacility(id="facility-2", name="Recycler Ltd", registration_number="RC-124",
                                address="Second location", authorization_status="AUTHORIZED",
                                permitted_waste_categories=["WEEE Category 1"]))
        db.add(FacilityMembership(user_id="recycler-coworker", facility_id="facility-2", active=True, verified=True))
        db.commit()

        claim = create_claim(db)
        claim_id = claim["id"]
        assert claim["audit_history"][0]["actor"]["role"] == "PRODUCER"
        assert claims_api._load_claim(claim_id, db, coworker).id == claim_id
        # A legacy assignment without its facility key fails closed pending review.
        claim_row = db.get(Claim, claim_id)
        claim_row.recycler_facility_id = None
        db.commit()
        with pytest.raises(HTTPException) as unmapped:
            claims_api._load_claim(claim_id, db, coworker)
        assert unmapped.value.status_code == 404
        claim_row.recycler_facility_id = "facility-1"
        db.commit()
        second_facility_claim = create_claim(db, recycler_facility_id="facility-2")
        assert claims_api._load_claim(second_facility_claim["id"], db, coworker).id == second_facility_claim["id"]
        with pytest.raises(HTTPException) as forbidden:
            claims_api._load_claim(claim_id, db, other)
        assert forbidden.value.status_code == 404

        claims_api.confirm_receipt(
            claim_id,
            ReceiptConfirmation(received_weight_kg=98, received_at="2026-10-08T11:00:00Z"),
            db, coworker,
        )
        assert claims_api.get_claim(claim_id, db, coworker)["audit_history"][-1]["actor"]["role"] == "RECYCLER"
        with pytest.raises(ValidationError):
            ProcessingSubmission(batches=[{
                "processed_output_kg": 0,
                "recovered_materials": [],
                "residual_waste_kg": 0,
                "processing_date": "2026-10-09",
            }])
        with pytest.raises(ValidationError):
            ProcessingSubmission(batches=[{
                "processed_output_kg": 1,
                "recovered_materials": [],
                "residual_waste_kg": 0,
                "processing_date": "not-a-date",
            }])

        complete = claims_api.submit_processing(
            claim_id,
            ProcessingSubmission(batches=[
                {"processed_output_kg": 40, "recovered_materials": [{"material": "Copper", "quantity_kg": 30}],
                 "residual_waste_kg": 10, "processing_date": "2026-10-09"},
                {"processed_output_kg": 40, "recovered_materials": [{"material": "Copper", "quantity_kg": 30}],
                 "residual_waste_kg": 10, "processing_date": "2026-10-10"},
            ]),
            db, coworker,
        )
        assert complete["mass_balance"]["declared_input_kg"] == 100
        assert complete["mass_balance"]["processed_output_kg"] == 80
        assert complete["mass_balance"]["recovered_materials"][0]["quantity_kg"] == 60
        assert len(complete["processing_batches"]) == 2
        assert all(batch["submitted_by"]["user_id"] == coworker.id for batch in complete["processing_batches"])
        assert "PROCESSING_BATCH_SUBMITTED" in {event["action"] for event in complete["audit_history"]}

        official = db.get(User, "gov-1")
        prior_status = complete["status"]
        audited = claims_api.record_claim_audit_note(
            claim_id,
            AuditNoteBody(audit_type="ROUTINE", note="Compared receipt and processing evidence."),
            db,
            official,
        )
        assert audited["status"] == prior_status
        audit_event = audited["audit_history"][-1]
        assert audit_event["action"] == "ROUTINE_AUDIT_RECORDED"
        assert audit_event["actor"]["role"] == "GOV_OFFICIAL"
        assert audit_event["note"] == "Compared receipt and processing evidence."
        clarification = claims_api.request_claim_clarification(
            claim_id, RequestClarificationBody(reason="Please correct the batch total."), db, official,
        )
        assert clarification["status"] == "AWAITING_CLARIFICATION"
        receipt_corrected = claims_api.confirm_receipt(
            claim_id,
            ReceiptConfirmation(received_weight_kg=97, received_at="2026-10-08T11:05:00Z"),
            db, coworker,
        )
        receipt_event = next(event for event in receipt_corrected["audit_history"]
                             if event["action"] == "RECEIPT_CORRECTED")
        assert receipt_event["previous"]["received_weight_kg"] == 98
        clarification = claims_api.request_claim_clarification(
            claim_id, RequestClarificationBody(reason="Please correct the batch total."), db, official,
        )
        assert clarification["status"] == "AWAITING_CLARIFICATION"
        corrected = claims_api.submit_processing(
            claim_id,
            ProcessingSubmission(corrects_previous=True, batches=[{
                "processed_output_kg": 75,
                "recovered_materials": [{"material": "Copper", "quantity_kg": 55}],
                "residual_waste_kg": 20,
                "processing_date": "2026-10-10",
            }]),
            db, coworker,
        )
        assert corrected["mass_balance"]["declared_input_kg"] == 100
        assert corrected["mass_balance"]["processed_output_kg"] == 75
        actions = [event["action"] for event in corrected["audit_history"]]
        assert "CLARIFICATION_REQUESTED" in actions
        assert "PROCESSING_CORRECTION_REQUESTED" in actions
        assert "PROCESSING_BATCH_CORRECTED" in actions
        assert "CLAIM_SUBMITTED" in actions


def test_missing_stage_evidence_is_informational_not_a_risk_penalty(db_factory):
    with db_factory() as db:
        complete = create_complete_claim(db)
        result = complete["verification_result"]
        missing = [flag for flag in result["flags"] if flag["code"].startswith("EVIDENCE_MISSING_")]
        assert missing
        assert all(flag["severity"] == "INFO" and flag["risk_contribution"] == 0 for flag in missing)
        assert result["risk_score"] == 0


def test_verification_rerun_keeps_mass_gps_and_duplicate_flags(db_factory):
    content = b"%PDF-1.4\nreused evidence\n"
    with db_factory() as db:
        claim = create_claim(
            db,
            destination_lat=30,
            destination_lng=30,
        )
        upload_pdf(claim["id"], "one.pdf", content, db)
        confirm_and_process(db, claim["id"], received_weight=70, output=120, recovered=80, residual=20)
        uploaded = upload_pdf(claim["id"], "two.pdf", content, db, "recycler-1")
        events_before_rerun = db.query(AuditEvent).filter_by(claim_id=claim["id"]).count()
        rerun = claims_api.trigger_verification(claim["id"], db, db.get(User, "user-1"))
        events_after_rerun = db.query(AuditEvent).filter_by(claim_id=claim["id"]).count()

    codes = {flag["code"] for flag in rerun["verification_result"]["flags"]}
    assert {"MB_VARIANCE_CRITICAL", "MB_TRANSPORT_SHORTFALL", "GEO_IMPOSSIBLE_TRANSIT", "DUPLICATE_SHA256"} <= codes
    assert rerun["verification_result"]["risk_score"] == uploaded["verification_result"]["risk_score"]
    assert events_after_rerun == events_before_rerun
    current = [item for item in rerun["verification_result"]["flags"] if item.get("status") == "ACTIVE"]
    assert all(item.get("flag_id") and item.get("rule_version") for item in current)


def test_corrected_discrepancies_resolve_and_keep_score_history(db_factory):
    with db_factory() as db:
        claim = create_claim(db)
        complete = confirm_and_process(db, claim["id"], received_weight=70, output=120, recovered=80, residual=20)
        initial = complete["verification_result"]
        assert initial["risk_score"] > 0
        claim_row = db.get(Claim, claim["id"])
        details = dict(claim_row.mass_balance_details or {})
        batches = [dict(item) for item in details["processing_batches"]]
        batches[0]["processed_output_kg"] = 80
        batches[0]["recovered_materials"] = [{"material": "Recovered", "quantity_kg": 60}]
        batches[0]["residual_waste_kg"] = 20
        details["processing_batches"] = batches
        claim_row.mass_balance_details = details
        claim_row.received_weight_kg = 100
        claim_row.processed_output_kg = 80
        claims_api._run_verification(claim_row, db, db.get(User, "user-1"))
        db.flush()
        corrected = claims_api.get_claim(claim["id"], db, db.get(User, "user-1"))["verification_result"]
        resolved = [item for item in corrected["flags"] if item.get("status") == "RESOLVED"]
        assert resolved
        assert corrected["risk_score"] == 0
        history = corrected["explainability"]["score_history"]
        assert len(history) >= 2
        resolution_times = {item["flag_id"]: item["resolved_at"] for item in resolved}
        claims_api._run_verification(claim_row, db, db.get(User, "user-1"))
        db.flush()
        rerun = claims_api.get_claim(claim["id"], db, db.get(User, "user-1"))["verification_result"]
        rerun_times = {item["flag_id"]: item["resolved_at"] for item in rerun["flags"] if item.get("status") == "RESOLVED"}
        assert rerun_times == resolution_times


def test_government_dismissal_records_reason_and_recalculates_score(db_factory):
    with db_factory() as db:
        complete = create_claim(db)
        result = confirm_and_process(db, complete["id"], received_weight=70, output=120, recovered=80, residual=20)
        claim_id = result["id"]
        official = db.get(User, "gov-1")
        active = next(item for item in result["verification_result"]["flags"] if item.get("status") == "ACTIVE")
        old_score = result["verification_result"]["risk_score"]
        updated = claims_api.dismiss_verification_flag(
            claim_id, active["flag_id"], FlagDismissBody(reason="Reviewed source records; discrepancy is documented."), db, official
        )
        dismissed = next(item for item in updated["verification_result"]["flags"] if item["flag_id"] == active["flag_id"])
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["resolution_reason"] == "Reviewed source records; discrepancy is documented."
        assert updated["verification_result"]["risk_score"] <= old_score
        assert db.query(AuditEvent).filter_by(claim_id=claim_id, action_type="VERIFICATION_FLAG_DISMISSED").count() == 1
