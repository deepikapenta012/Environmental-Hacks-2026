"""Tests for secure evidence storage, versioning, authorization, and file validation."""

import hashlib
import io
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile

from app.api import claims as claims_api
from app.database import Base
from app.models import (
    AuditEvent, Claim, Evidence, EvidenceVersion, FacilityMembership,
    RecyclerFacility, GovernmentJurisdiction, GovernmentJurisdictionAssignment,
    User, VerificationResult,
)
from app.auth import hash_password
from app.schemas import ClaimCreate
from app.services.storage import LocalStorageBackend, set_storage_backend, get_storage_backend


# ── Fixtures ─────────────────────────────────────────────────────────────

VALID_PDF = b"%PDF-1.4 test content " + b"x" * 100
VALID_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
VALID_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100

# Use a project-local scratch directory to avoid Windows temp permission issues
SCRATCH_ROOT = os.path.join(os.path.dirname(__file__), ".test_scratch")


@pytest.fixture
def local_tmp():
    """Create a unique local temp directory for each test."""
    path = os.path.join(SCRATCH_ROOT, uuid.uuid4().hex[:12])
    os.makedirs(path, exist_ok=True)
    from pathlib import Path
    yield Path(path)
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def db_factory(local_tmp):
    engine = create_engine(
        f"sqlite:///{local_tmp / 'test.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    password_hash, password_salt = hash_password("test-password")

    # Set up test storage backend
    storage_root = local_tmp / "evidence_store"
    storage_root.mkdir()
    set_storage_backend(LocalStorageBackend(root=storage_root))

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
        db.add(RecyclerFacility(
            id="facility-1", name="Recycler Ltd", registration_number="RC-123",
            address="Test", authorization_status="AUTHORIZED",
            permitted_waste_categories=["WEEE Category 1"],
        ))
        db.add(FacilityMembership(user_id="recycler-1", facility_id="facility-1", active=True, verified=True))
        db.add(GovernmentJurisdiction(
            id="jurisdiction-1", name="Test Area",
            boundary=[[76.0, 12.0], [79.0, 12.0], [79.0, 14.0], [76.0, 14.0]],
        ))
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


def make_upload(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


# ── Storage Abstraction Tests ────────────────────────────────────────────


class TestLocalStorageBackend:
    def test_save_and_load(self, local_tmp):
        storage = LocalStorageBackend(root=local_tmp / "store")
        content = b"test file content"
        key = storage.save("claim-123", ".pdf", content)
        assert key.startswith("claim-123/")
        assert key.endswith(".pdf")
        loaded = storage.load(key)
        assert loaded == content

    def test_save_generates_unique_names(self, local_tmp):
        storage = LocalStorageBackend(root=local_tmp / "store")
        key1 = storage.save("claim-1", ".pdf", b"content-1")
        key2 = storage.save("claim-1", ".pdf", b"content-2")
        assert key1 != key2

    def test_exists(self, local_tmp):
        storage = LocalStorageBackend(root=local_tmp / "store")
        key = storage.save("claim-1", ".jpg", b"\xff\xd8\xff\xe0test")
        assert storage.exists(key)
        assert not storage.exists("nonexistent/file.pdf")

    def test_path_traversal_on_save_blocked(self, local_tmp):
        storage = LocalStorageBackend(root=local_tmp / "store")
        # Claim ID with path traversal should be sanitised
        key = storage.save("../../etc", ".pdf", b"malicious")
        assert ".." not in key
        assert storage.exists(key)

    def test_path_traversal_on_load_blocked(self, local_tmp):
        storage = LocalStorageBackend(root=local_tmp / "store")
        with pytest.raises(FileNotFoundError):
            storage.resolve_path("../../etc/passwd")

    def test_resolve_path_rejects_dots(self, local_tmp):
        storage = LocalStorageBackend(root=local_tmp / "store")
        with pytest.raises(FileNotFoundError):
            storage.resolve_path("../something.pdf")

    def test_sanitise_claim_id(self, local_tmp):
        storage = LocalStorageBackend(root=local_tmp / "store")
        # Special characters should be stripped
        key = storage.save("claim/../../etc", ".pdf", b"%PDF-test")
        # The key should be safe
        path = storage.resolve_path(key)
        assert path.is_relative_to(storage.root)


# ── File Validation Tests ────────────────────────────────────────────────


class TestFileValidation:
    def test_valid_pdf_upload(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            claim_id = result["id"]
            file = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                claim_id, file, db, db.get(User, "user-1"),
                category="COLLECTION_WEIGHT_SLIP",
            )
            assert any(e["category"] == "COLLECTION_WEIGHT_SLIP" for e in response["evidence"])

    def test_valid_jpeg_upload(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_JPEG, "photo.jpg", "image/jpeg")
            response = claims_api.upload_evidence(
                result["id"], file, db, db.get(User, "user-1"),
                category="COLLECTION_WEIGHT_SLIP",
            )
            assert len(response["evidence"]) >= 1

    def test_reject_empty_file(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(b"", "empty.pdf", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(result["id"], file, db, db.get(User, "user-1"))
            assert exc.value.status_code == 400
            assert "empty" in exc.value.detail.lower()

    def test_reject_oversized_file(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            big_content = b"%PDF-" + b"x" * (10 * 1024 * 1024 + 1)
            file = make_upload(big_content, "big.pdf", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(result["id"], file, db, db.get(User, "user-1"))
            assert exc.value.status_code == 413

    def test_reject_wrong_extension(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.exe", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(result["id"], file, db, db.get(User, "user-1"))
            assert exc.value.status_code == 400

    def test_reject_mime_mismatch(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.pdf", "image/jpeg")
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(result["id"], file, db, db.get(User, "user-1"))
            assert exc.value.status_code == 400
            assert "content type" in exc.value.detail.lower()

    def test_reject_invalid_signature(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            # PDF extension but JPEG content type, wrong signature
            file = make_upload(b"NOT-A-PDF-FILE" + b"x" * 100, "test.pdf", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(result["id"], file, db, db.get(User, "user-1"))
            assert exc.value.status_code == 400

    def test_reject_malicious_filename(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "../../../etc/passwd.pdf", "application/pdf")
            # Should succeed but the stored filename should be sanitised
            response = claims_api.upload_evidence(
                result["id"], file, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev = response["evidence"][-1]
            assert ".." not in ev["filename"]
            assert "/" not in ev["filename"]
            assert "\\" not in ev["filename"]


# ── Authorization Tests ──────────────────────────────────────────────────


class TestEvidenceAuthorization:
    def test_gov_official_cannot_upload(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(
                    result["id"], file, db, db.get(User, "gov-1")
                )
            assert exc.value.status_code == 403

    def test_other_producer_cannot_upload(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(
                    result["id"], file, db, db.get(User, "user-2")
                )
            # Other producer's claim should be 404 (scope filter)

    def test_other_producer_cannot_download(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev_id = response["evidence"][-1]["id"]
            with pytest.raises(HTTPException) as exc:
                claims_api.download_evidence(result["id"], ev_id, db, db.get(User, "user-2"))
            assert exc.value.status_code == 404

    def test_download_checks_stored_file_integrity(self, db_factory):
        with db_factory() as db:
            claim = create_claim(db)
            uploaded = claims_api.upload_evidence(claim["id"], make_upload(VALID_PDF, "proof.pdf", "application/pdf"),
                db, db.get(User, "user-1"), category="OTHER_SUPPORTING")
            item = db.query(Evidence).filter_by(claim_id=claim["id"]).one()
            storage = get_storage_backend()
            storage.resolve_path(item.storage_key).write_bytes(b"tampered")
            with pytest.raises(HTTPException) as exc:
                claims_api.download_evidence(claim["id"], item.id, db, db.get(User, "user-1"))
            assert exc.value.status_code == 409


# ── Versioning Tests ─────────────────────────────────────────────────────


class TestEvidenceVersioning:
    def test_upload_creates_version_record(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "document.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file, db, db.get(User, "user-1"),
                category="COLLECTION_WEIGHT_SLIP",
            )
            ev = response["evidence"][-1]
            assert ev["version_number"] == 1
            assert ev["status"] == "ACTIVE"
            assert ev.get("logical_id")

            # Check version record exists in DB
            versions = db.query(EvidenceVersion).filter_by(evidence_id=ev["id"]).all()
            assert len(versions) == 1
            assert versions[0].version_number == 1
            assert versions[0].status == "ACTIVE"

    def test_replace_preserves_previous_version(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            # Upload original
            file1 = make_upload(VALID_PDF, "original.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="COLLECTION_WEIGHT_SLIP",
            )
            ev_id = response["evidence"][-1]["id"]
            original_sha = response["evidence"][-1]["sha256"]

            # Replace
            file2 = make_upload(VALID_PDF + b"UPDATED", "updated.pdf", "application/pdf")
            response2 = claims_api.replace_evidence(
                result["id"], ev_id, file2,
                replacement_reason="Updated with corrected weight data",
                db=db, current_user=db.get(User, "user-1"),
            )

            # Original should be superseded
            old_ev = db.get(Evidence, ev_id)
            assert old_ev.status == "SUPERSEDED"
            assert old_ev.replaced_by_id is not None

            # New evidence should be active
            active_evidence = [e for e in response2["evidence"] if e["status"] == "ACTIVE"]
            assert len(active_evidence) >= 1
            new_ev = next(e for e in active_evidence if e["category"] == "COLLECTION_WEIGHT_SLIP")
            assert new_ev["version_number"] == 2
            assert new_ev["sha256"] != original_sha

    def test_version_history_endpoint(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            # Upload and replace
            file1 = make_upload(VALID_PDF, "v1.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="COLLECTION_WEIGHT_SLIP",
            )
            ev_id = response["evidence"][-1]["id"]

            file2 = make_upload(VALID_PDF + b"V2", "v2.pdf", "application/pdf")
            claims_api.replace_evidence(
                result["id"], ev_id, file2,
                replacement_reason="Version 2 update",
                db=db, current_user=db.get(User, "user-1"),
            )

            # Get version history
            history = claims_api.get_evidence_versions(
                result["id"], ev_id, db, db.get(User, "user-1"),
            )
            assert len(history["versions"]) == 2
            assert history["versions"][0]["version_number"] > history["versions"][1]["version_number"]


# ── Audit Recording Tests ────────────────────────────────────────────────


class TestEvidenceAuditRecording:
    def test_upload_records_audit_event(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            claims_api.upload_evidence(
                result["id"], file, db, db.get(User, "user-1"),
                category="COLLECTION_WEIGHT_SLIP",
            )
            events = db.query(AuditEvent).filter_by(claim_id=result["id"]).all()
            upload_events = [e for e in events if e.action_type == "EVIDENCE_UPLOADED"]
            assert len(upload_events) >= 1

    def test_replace_records_audit_event(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file1 = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev_id = response["evidence"][-1]["id"]
            file2 = make_upload(VALID_PDF + b"new", "test2.pdf", "application/pdf")
            claims_api.replace_evidence(
                result["id"], ev_id, file2,
                replacement_reason="Corrected document",
                db=db, current_user=db.get(User, "user-1"),
            )
            events = db.query(AuditEvent).filter_by(claim_id=result["id"]).all()
            replace_events = [e for e in events if e.action_type == "EVIDENCE_REPLACED"]
            assert len(replace_events) >= 1
            assert replace_events[0].reason == "Corrected document"

    def test_archive_records_audit_event(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev_id = response["evidence"][-1]["id"]
            claims_api.archive_evidence(
                result["id"], ev_id,
                reason="No longer relevant",
                db=db, current_user=db.get(User, "user-1"),
            )
            events = db.query(AuditEvent).filter_by(claim_id=result["id"]).all()
            archive_events = [e for e in events if e.action_type == "EVIDENCE_ARCHIVED"]
            assert len(archive_events) >= 1
            archived = db.query(EvidenceVersion).filter_by(evidence_id=ev_id).one()
            assert archived.status == "ARCHIVED"


# ── SHA-256 Hash Tests ───────────────────────────────────────────────────


class TestDuplicateHashes:
    def test_same_file_different_uploads_same_hash(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            content = VALID_PDF + b"unique-content-for-hash-test"
            expected_hash = hashlib.sha256(content).hexdigest()

            file1 = make_upload(content, "doc1.pdf", "application/pdf")
            response1 = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="COLLECTION_WEIGHT_SLIP",
            )
            assert response1["evidence"][-1]["sha256"] == expected_hash

            file2 = make_upload(content, "doc2.pdf", "application/pdf")
            response2 = claims_api.upload_evidence(
                result["id"], file2, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            assert response2["evidence"][-1]["sha256"] == expected_hash


# ── Evidence Replacement Rule Tests ──────────────────────────────────────


class TestEvidenceReplacementRules:
    def test_no_flags_for_single_version(self):
        from app.verification.rules import check_evidence_replacements
        evidence = [
            {"id": "ev1", "logical_id": "evl1", "sha256": "abc123", "status": "ACTIVE"},
        ]
        flags = check_evidence_replacements(evidence, claim_status="PENDING", has_verification_result=False)
        assert len(flags) == 0

    def test_flags_replacement_after_review(self):
        from app.verification.rules import check_evidence_replacements
        evidence = [
            {"id": "ev1", "logical_id": "evl1", "sha256": "abc123", "status": "SUPERSEDED"},
            {"id": "ev2", "logical_id": "evl1", "sha256": "def456", "status": "PENDING_REVIEW"},
        ]
        flags = check_evidence_replacements(evidence, claim_status="PENDING", has_verification_result=True)
        assert any(f.code == "EVIDENCE_REPLACED_AFTER_REVIEW" for f in flags)

    def test_flags_excessive_replacements(self):
        from app.verification.rules import check_evidence_replacements
        evidence = [
            {"id": "ev1", "logical_id": "evl1", "sha256": "a", "status": "SUPERSEDED"},
            {"id": "ev2", "logical_id": "evl1", "sha256": "b", "status": "SUPERSEDED"},
            {"id": "ev3", "logical_id": "evl1", "sha256": "c", "status": "ACTIVE"},
        ]
        flags = check_evidence_replacements(evidence, claim_status="RECEIVED", has_verification_result=False)
        assert any(f.code == "EVIDENCE_EXCESSIVE_REPLACEMENTS" for f in flags)

    def test_flags_duplicate_active_hashes(self):
        from app.verification.rules import check_evidence_replacements
        evidence = [
            {"id": "ev1", "logical_id": "evl1", "sha256": "same_hash", "status": "ACTIVE"},
            {"id": "ev2", "logical_id": "evl2", "sha256": "same_hash", "status": "ACTIVE"},
        ]
        flags = check_evidence_replacements(evidence, claim_status="RECEIVED", has_verification_result=False)
        assert any(f.code == "EVIDENCE_DUPLICATE_HASH_ACTIVE" for f in flags)


# ── Evidence Cannot Be Erased Tests ──────────────────────────────────────


class TestEvidencePreservation:
    def test_superseded_evidence_still_accessible(self, db_factory):
        """Superseded evidence must remain downloadable (never erased)."""
        with db_factory() as db:
            result = create_claim(db)
            file1 = make_upload(VALID_PDF, "original.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev_id = response["evidence"][-1]["id"]

            file2 = make_upload(VALID_PDF + b"replaced", "replaced.pdf", "application/pdf")
            claims_api.replace_evidence(
                result["id"], ev_id, file2,
                replacement_reason="Correction",
                db=db, current_user=db.get(User, "user-1"),
            )

            # Original evidence should still be downloadable
            file_response = claims_api.download_evidence(
                result["id"], ev_id, db, db.get(User, "user-1"),
            )
            assert file_response is not None

    def test_archived_evidence_still_accessible(self, db_factory):
        """Archived evidence must remain downloadable."""
        with db_factory() as db:
            result = create_claim(db)
            file1 = make_upload(VALID_PDF, "archived.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev_id = response["evidence"][-1]["id"]

            claims_api.archive_evidence(
                result["id"], ev_id,
                reason="Administrative archival",
                db=db, current_user=db.get(User, "user-1"),
            )

            # Archived evidence should still be downloadable
            file_response = claims_api.download_evidence(
                result["id"], ev_id, db, db.get(User, "user-1"),
            )
            assert file_response is not None


# ── Replace Authorization Tests ──────────────────────────────────────────


class TestReplacementAuthorization:
    def test_gov_official_cannot_replace(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file1 = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev_id = response["evidence"][-1]["id"]
            file2 = make_upload(VALID_PDF + b"new", "test2.pdf", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.replace_evidence(
                    result["id"], ev_id, file2,
                    replacement_reason="Test",
                    db=db, current_user=db.get(User, "gov-1"),
                )
            # Gov official cannot see this claim via scope filter
            assert exc.value.status_code in {403, 404}

    def test_replace_requires_reason(self, db_factory):
        """Replacement reason must be at least 3 characters."""
        with db_factory() as db:
            result = create_claim(db)
            file1 = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            response = claims_api.upload_evidence(
                result["id"], file1, db, db.get(User, "user-1"),
                category="OTHER_SUPPORTING",
            )
            ev_id = response["evidence"][-1]["id"]
            file2 = make_upload(VALID_PDF + b"new", "test2.pdf", "application/pdf")
            # Short reason should fail (FastAPI Form validation)
            # The endpoint requires min_length=3
            with pytest.raises(Exception):
                claims_api.replace_evidence(
                    result["id"], ev_id, file2,
                    replacement_reason="ab",  # too short
                    db=db, current_user=db.get(User, "user-1"),
                )

    def test_cannot_replace_nonexistent_evidence(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            file = make_upload(VALID_PDF, "test.pdf", "application/pdf")
            with pytest.raises(HTTPException) as exc:
                claims_api.replace_evidence(
                    result["id"], "nonexistent-id", file,
                    replacement_reason="Test reason",
                    db=db, current_user=db.get(User, "user-1"),
                )
            assert exc.value.status_code == 404

    def test_replacement_reopens_reviewed_claim_and_requires_review(self, db_factory):
        with db_factory() as db:
            result = create_claim(db)
            claim = db.get(Claim, result["id"])
            claim.received_at = None
            claim.status = "APPROVED"
            evidence = Evidence(id="reviewed-ev", claim_id=claim.id, logical_id="reviewed-logical",
                type="CERTIFICATE", filename="recycler.pdf", file_path="missing.pdf", storage_key="missing.pdf",
                sha256=hashlib.sha256(VALID_PDF).hexdigest(), size_bytes=len(VALID_PDF), source="RECYCLER",
                category="OTHER_SUPPORTING", uploaded_by_user_id="recycler-1", uploader_role="RECYCLER_EMPLOYEE",
                status="ACTIVE", version_number=1)
            db.add(evidence)
            db.commit()
            replacement = claims_api.replace_evidence(claim.id, evidence.id,
                make_upload(VALID_PDF + b"corrected", "revised.pdf", "application/pdf"),
                replacement_reason="Corrected source record", db=db, current_user=db.get(User, "recycler-1"))
            new = next(item for item in replacement["evidence"] if item["id"] != evidence.id)
            assert new["status"] == "PENDING_REVIEW"
            assert replacement["status"] == "PENDING"
            assert any(event["action"] == "VERIFICATION_REOPENED_EVIDENCE_CHANGE"
                       for event in replacement["audit_history"])

    def test_replacement_rejects_whitespace_reason(self, db_factory):
        with db_factory() as db:
            claim = create_claim(db)
            uploaded = claims_api.upload_evidence(claim["id"], make_upload(VALID_PDF, "doc.pdf", "application/pdf"),
                db, db.get(User, "user-1"), category="OTHER_SUPPORTING")
            evidence_id = uploaded["evidence"][0]["id"]
            with pytest.raises(HTTPException) as exc:
                claims_api.replace_evidence(claim["id"], evidence_id,
                    make_upload(VALID_PDF + b"new", "new.pdf", "application/pdf"),
                    replacement_reason="   ", db=db, current_user=db.get(User, "user-1"))
            assert exc.value.status_code == 422

    def test_invalid_operational_link_is_rejected(self, db_factory):
        with db_factory() as db:
            claim = create_claim(db)
            with pytest.raises(HTTPException) as exc:
                claims_api.upload_evidence(claim["id"], make_upload(VALID_PDF, "doc.pdf", "application/pdf"),
                    db, db.get(User, "user-1"), category="OTHER_SUPPORTING",
                    linked_entity_type="TRANSPORT_LEG", linked_entity_id="belongs-to-someone-else")
            assert exc.value.status_code == 422

    def test_concurrent_replacements_preserve_a_single_active_revision(self, db_factory):
        with db_factory() as db:
            claim = create_claim(db)
            uploaded = claims_api.upload_evidence(claim["id"], make_upload(VALID_PDF, "doc.pdf", "application/pdf"),
                db, db.get(User, "user-1"), category="OTHER_SUPPORTING")
            claim_id, evidence_id = claim["id"], uploaded["evidence"][0]["id"]
        def replace(suffix):
            with db_factory() as session:
                try:
                    claims_api.replace_evidence(claim_id, evidence_id,
                        make_upload(VALID_PDF + suffix, "revision.pdf", "application/pdf"),
                        replacement_reason="Concurrent corrected document", db=session,
                        current_user=session.get(User, "user-1"))
                    return "replaced"
                except HTTPException as exc:
                    return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(replace, (b"one", b"two")))
        assert results.count("replaced") == 1
        with db_factory() as db:
            revisions = db.query(Evidence).filter_by(claim_id=claim_id, logical_id=uploaded["evidence"][0]["logical_id"]).all()
            assert sum(item.status in {"ACTIVE", "PENDING_REVIEW"} for item in revisions) == 1
