import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import api_router
from app import auth as auth_module
from app.auth import hash_password
from app.config import Settings
from app.database import Base, get_db
from app.models import (User, RecyclerFacility, FacilityMembership,
                        GovernmentJurisdiction, GovernmentJurisdictionAssignment)
from app.services.storage import LocalStorageBackend, set_storage_backend


def test_authentication_roles_and_claim_ownership(monkeypatch, tmp_path):
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: Settings(jwt_secret_key="test-only-secret-key-with-32-chars"),
    )
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with factory() as db:
        for user_id, username, persona, organisation, role in (
            ("producer-one", "producer.one", "USER", "Producer Ltd", "PRODUCER"),
            ("producer-two", "producer.two", "USER", "Other Producer Ltd", "PRODUCER"),
            ("recycler-one", "recycler.one", "USER", "Recycler Ltd", "RECYCLER_EMPLOYEE"),
            ("recycler-coworker", "recycler.coworker", "USER", "Recycler Ltd", "RECYCLER_EMPLOYEE"),
            ("recycler-other", "recycler.other", "USER", "Different Recycler Ltd", "RECYCLER_EMPLOYEE"),
            ("official-one", "official.one", "GOV_OFFICIAL", "Government", "GOVERNMENT_OFFICER"),
        ):
            password_hash, password_salt = hash_password("correct-horse-battery")
            db.add(User(
                id=user_id,
                username=username,
                password_hash=password_hash,
                password_salt=password_salt,
                display_name=username,
                organisation=organisation,
                persona=persona,
                role=role,
            ))
        db.add(RecyclerFacility(id="facility-one", name="Recycler Ltd", registration_number="RC-123",
                                address="Facility Address", authorization_status="AUTHORIZED",
                                permitted_waste_categories=["WEEE Category 1"]))
        db.add(RecyclerFacility(id="facility-other", name="Different Recycler Ltd", registration_number="RC-999",
                                address="Other Address", authorization_status="AUTHORIZED",
                                permitted_waste_categories=["WEEE Category 1"]))
        for employee in ("recycler-one", "recycler-coworker"):
            db.add(FacilityMembership(user_id=employee, facility_id="facility-one", active=True, verified=True))
        db.add(FacilityMembership(user_id="recycler-other", facility_id="facility-other", active=True, verified=True))
        db.add(GovernmentJurisdiction(id="jurisdiction-one", name="Test Region",
                                      boundary=[[76, 12], [79, 12], [79, 14], [76, 14]]))
        db.add(GovernmentJurisdictionAssignment(user_id="official-one", jurisdiction_id="jurisdiction-one"))
        db.commit()

    app = FastAPI()
    app.include_router(api_router)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    from app.api import claims as claims_api
    set_storage_backend(LocalStorageBackend(tmp_path / "evidence_store"))
    client = TestClient(app)

    assert client.get("/api/v1/claims/").status_code == 401

    def login(username):
        response = client.post("/api/v1/auth/login", json={
            "username": username,
            "password": "correct-horse-battery",
        })
        assert response.status_code == 200
        assert response.json()["token_type"] == "bearer"
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    producer_one = login("producer.one")
    producer_two = login("producer.two")
    recycler = login("recycler.one")
    recycler_coworker = login("recycler.coworker")
    other_recycler = login("recycler.other")
    official = login("official.one")

    assert client.get("/api/v1/claims/verification/rules", headers=producer_one).status_code == 403
    rules = client.get("/api/v1/claims/verification/rules", headers=official)
    assert rules.status_code == 200
    assert rules.json()["score_range"] == [0, 100]
    assert any(rule["rule_id"] == "MB-002" for rule in rules.json()["rules"])

    payload = {
        "producer_name": "Producer Ltd",
        "producer_registration_number": "PR-123",
        "recycler_name": "Recycler Ltd",
        "recycler_registration_number": "RC-123",
        "recycler_facility_id": "facility-one",
        "role": "GOVERNMENT_OFFICER",  # Untrusted request role must have no effect.
        "waste_category": "WEEE Category 1",
        "declared_weight_kg": 500,
        # These untrusted legacy fields must be ignored on producer submission.
        "received_weight_kg": 492,
        "processed_output_kg": 480,
        "recovered_materials": [{"material": "Recovered", "quantity_kg": 420}],
        "residual_waste_kg": 60,
        "collection_date": "2026-10-08",
        "vehicle_registration": "KA-01-AA-1000",
        "driver_name": "Test Driver",
        "origin_lat": 12.9,
        "origin_lng": 77.5,
        "destination_lat": 13.0,
        "destination_lng": 77.6,
        "departed_at": "2026-10-08T09:00:00",
        "arrived_at": "2026-10-08T10:00:00",
    }
    first = client.post("/api/v1/claims/", json=payload, headers=producer_one)
    second = client.post("/api/v1/claims/", json=payload, headers=producer_two)
    assert first.status_code == second.status_code == 201
    claim_id = first.json()["id"]
    initial = first.json()
    assert initial["status"] == "AWAITING_RECYCLER_CONFIRMATION"
    assert initial["mass_balance"]["declared_input_kg"] == 500
    assert initial["mass_balance"]["received_input_kg"] is None
    assert initial["mass_balance"]["processed_output_kg"] is None
    assert initial["verification_result"] is None
    assert client.post(
        f"/api/v1/claims/{claim_id}/flags/flg_example/dismiss",
        json={"reason": "Not authorized to dismiss findings"},
        headers=producer_one,
    ).status_code == 403
    with factory() as db:
        assert db.get(User, "producer-one").role == "PRODUCER"

    # Producer lists are owner-scoped, and an unrelated producer cannot fetch this claim.
    assert [claim["id"] for claim in client.get("/api/v1/claims/", headers=producer_one).json()["items"]] == [claim_id]
    assert client.get(f"/api/v1/claims/{claim_id}", headers=producer_two).status_code == 404

    # Producer cannot confirm receipt or submit recycler processing values.
    assert client.post(
        f"/api/v1/claims/{claim_id}/receipt",
        json={"received_weight_kg": 492, "received_at": "2026-10-08T11:00:00Z"},
        headers=producer_one,
    ).status_code == 403
    assert client.post(
        f"/api/v1/claims/{claim_id}/processing",
        json={
            "processed_output_kg": 1,
            "recovered_materials_total_kg": 1,
            "residual_waste_kg": 0,
            "processing_date": "2026-10-09",
        },
        headers=producer_one,
    ).status_code == 403
    assert client.post(
        f"/api/v1/claims/{claim_id}/receipt",
        json={"received_weight_kg": 492, "received_at": "2026-10-08T11:00:00Z"},
        headers=producer_two,
    ).status_code == 404
    assert client.post(
        f"/api/v1/claims/{claim_id}/receipt",
        json={"received_weight_kg": 492, "received_at": "2026-10-08T11:00:00Z"},
        headers=official,
    ).status_code == 403

    assigned = client.get("/api/v1/claims/assigned", headers=recycler).json()
    assert claim_id in {item["id"] for item in assigned}
    assert client.get(f"/api/v1/claims/{claim_id}", headers=recycler).status_code == 200
    assert client.get(f"/api/v1/claims/{claim_id}", headers=recycler_coworker).status_code == 200
    assert client.get(f"/api/v1/claims/{claim_id}", headers=other_recycler).status_code == 404
    assert client.get(f"/api/v1/claims/{claim_id}/audit", headers=other_recycler).status_code == 404
    assert claim_id in {item["id"] for item in client.get("/api/v1/claims/assigned", headers=recycler_coworker).json()}
    assert claim_id not in {item["id"] for item in client.get("/api/v1/claims/assigned", headers=other_recycler).json()}
    # A same-organization account without verified membership receives no claim data.
    with factory() as db:
        membership = db.query(FacilityMembership).filter_by(user_id="recycler-coworker", facility_id="facility-one").one()
        membership.verified = False
        db.commit()
    assert client.get(f"/api/v1/claims/{claim_id}", headers=recycler_coworker).status_code == 404
    with factory() as db:
        membership = db.query(FacilityMembership).filter_by(user_id="recycler-coworker", facility_id="facility-one").one()
        membership.verified = True
        db.commit()

    producer_evidence = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        headers=producer_one,
        data={
            "category": "COLLECTION_WEIGHT_SLIP",
            "document_data": json.dumps({
                "producer": "Producer Ltd",
                "recycler": "Recycler Ltd",
                "quantity": 500,
                "date": "2026-10-08",
                "material_type": "WEEE Category 1",
            }),
        },
        files={"file": ("producer.pdf", b"%PDF-1.4\nproducer proof\n", "application/pdf")},
    )
    assert producer_evidence.status_code == 201
    producer_file = producer_evidence.json()["evidence"][0]
    assert producer_file["source"] == "PRODUCER"
    assert producer_file["category"] == "COLLECTION_WEIGHT_SLIP"
    assert producer_file["uploaded_by"]["id"] == "producer-one"
    assert producer_file["verification_status"] == "METADATA_PROVIDED"
    assert producer_file["extraction_provenance"]["field_sources"]["producer"] == "UPLOADER_PROVIDED"
    assert "Declared-to-received mass reconciliation" in producer_file["verification_checks"]
    assert client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        headers=producer_one,
        data={"category": "RECYCLER_RECEIPT"},
        files={"file": ("forbidden.pdf", b"%PDF-1.4\nforbidden\n", "application/pdf")},
    ).status_code == 403

    receipt = client.post(
        f"/api/v1/claims/{claim_id}/receipt",
        json={"received_weight_kg": 492, "received_at": "2026-10-08T11:00:00Z", "recycler_notes": "Receipt weighed at gate."},
        headers=recycler,
    )
    assert receipt.status_code == 200
    assert receipt.json()["mass_balance"]["declared_input_kg"] == 500
    assert receipt.json()["mass_balance"]["received_input_kg"] == 492
    assert receipt.json()["audit_history"][-1]["action"] == "RECEIPT_CONFIRMED"
    assert receipt.json()["audit_history"][-1]["actor"]["user_id"] == "recycler-one"

    # An employee at the assigned facility may upload on its behalf; another facility cannot.
    coworker_evidence = client.post(
        f"/api/v1/claims/{claim_id}/evidence", headers=recycler_coworker,
        data={"category": "OTHER_SUPPORTING"},
        files={"file": ("same-receipt.pdf", b"%PDF-1.4\nrecycler proof\n", "application/pdf")},
    )
    assert coworker_evidence.status_code == 201
    assert next(item for item in coworker_evidence.json()["evidence"] if item["filename"] == "same-receipt.pdf")["uploaded_by"]["id"] == "recycler-coworker"
    assert client.post(
        f"/api/v1/claims/{claim_id}/evidence", headers=other_recycler,
        data={"category": "OTHER_SUPPORTING"},
        files={"file": ("outside.pdf", b"%PDF-1.4\noutside\n", "application/pdf")},
    ).status_code == 404

    invalid_processing = client.post(
        f"/api/v1/claims/{claim_id}/processing", headers=recycler,
        json={"batches": [{"processed_output_kg": 0, "recovered_materials": [],
                           "residual_waste_kg": 0, "processing_date": "2026-10-09"}]},
    )
    assert invalid_processing.status_code == 422

    recycler_evidence = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        headers=recycler,
        data={"category": "RECYCLER_RECEIPT"},
        files={"file": ("weighbridge.pdf", b"%PDF-1.4\nrecycler proof\n", "application/pdf")},
    )
    assert recycler_evidence.status_code == 201
    receipt_file = next(item for item in recycler_evidence.json()["evidence"] if item["category"] == "RECYCLER_RECEIPT")
    assert receipt_file["source"] == "RECYCLER"
    assert receipt_file["uploaded_by"]["id"] == "recycler-one"
    downloaded = client.get(
        f"/api/v1/claims/{claim_id}/evidence/{receipt_file['id']}/file",
        headers=official,
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.4\nrecycler proof\n"
    assert client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        headers=recycler,
        data={"category": "PROCESSING_RECOVERY"},
        files={"file": ("too-early.pdf", b"%PDF-1.4\nearly\n", "application/pdf")},
    ).status_code == 409

    processing = client.post(
        f"/api/v1/claims/{claim_id}/processing",
        headers=recycler,
        json={
            "batches": [
                {"batch_id": "batch-a", "processed_output_kg": 240,
                 "recovered_materials": [{"material": "Copper", "quantity_kg": 210}],
                 "residual_waste_kg": 30, "processing_date": "2026-10-09"},
                {"batch_id": "batch-b", "processed_output_kg": 240,
                 "recovered_materials": [{"material": "Copper", "quantity_kg": 210}],
                 "residual_waste_kg": 30, "processing_date": "2026-10-10"},
            ],
            "declared_weight_kg": 1,
        },
    )
    assert processing.status_code == 200
    complete = processing.json()
    assert complete["mass_balance"]["declared_input_kg"] == 500
    assert complete["mass_balance"]["received_input_kg"] == 492
    assert complete["mass_balance"]["processed_output_kg"] == 480
    assert complete["mass_balance"]["unexplained_difference_kg"] == 0
    assert complete["verification_result"] is not None
    assert len(complete["processing_batches"]) == 2
    assert complete["mass_balance"]["processed_output_kg"] == 480
    assert complete["mass_balance"]["recovered_materials"][0]["quantity_kg"] == 420
    assert "DUPLICATE_SHA256" in {flag["code"] for flag in complete["verification_result"]["flags"]}
    assert any(event["action"] == "PROCESSING_BATCH_SUBMITTED" for event in complete["audit_history"])

    processing_evidence = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        headers=recycler,
        data={"category": "PROCESSING_RECOVERY"},
        files={"file": ("processing.pdf", b"%PDF-1.4\nprocessing record\n", "application/pdf")},
    )
    assert processing_evidence.status_code == 201
    processing_file = next(item for item in processing_evidence.json()["evidence"] if item["category"] == "PROCESSING_RECOVERY")
    assert processing_file["verification_status"] == "PENDING_HUMAN_REVIEW"

    certificate = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        headers=recycler,
        data={"category": "RECYCLING_CERTIFICATE"},
        files={"file": ("certificate.pdf", b"%PDF-1.4\ncertificate\n", "application/pdf")},
    )
    assert certificate.status_code == 201

    audit_for_owner = client.get(f"/api/v1/claims/{claim_id}/audit", headers=producer_one)
    assert audit_for_owner.status_code == 200
    assert audit_for_owner.json()["chain_valid"] is True
    assert any(item["action_type"] == "RECEIPT_CONFIRMED" for item in audit_for_owner.json()["events"])
    receipt_event = next(item for item in audit_for_owner.json()["events"] if item["action_type"] == "RECEIPT_CONFIRMED")
    assert receipt_event["actor_user_id"] == "recycler-one"
    assert receipt_event["actor_role"] == "RECYCLER_EMPLOYEE"
    assert client.get(f"/api/v1/claims/{claim_id}/audit", headers=producer_two).status_code == 404
    certificate_id = next(item["id"] for item in certificate.json()["evidence"] if item["filename"] == "certificate.pdf")
    invalid_adjustment = client.post(f"/api/v1/claims/{claim_id}/adjustments", headers=recycler,
        json={"processing_batch_id": "batch-a", "field": "PROCESSED_OUTPUT", "corrected_quantity": -1,
              "category": "MEASUREMENT_CORRECTION", "reason": "A proper correction reason"})
    assert invalid_adjustment.status_code == 422
    missing_reason = client.post(f"/api/v1/claims/{claim_id}/adjustments", headers=recycler,
        json={"processing_batch_id": "batch-a", "field": "PROCESSED_OUTPUT", "corrected_quantity": 239,
              "category": "DATA_ENTRY_CORRECTION"})
    assert missing_reason.status_code == 422
    pending_adjustment = client.post(f"/api/v1/claims/{claim_id}/adjustments", headers=recycler,
        json={"processing_batch_id": "batch-a", "field": "PROCESSED_OUTPUT", "corrected_quantity": 230,
              "category": "MEASUREMENT_CORRECTION", "reason": "Corrected using the signed weighbridge ticket.",
              "supporting_evidence_ids": [certificate_id]})
    assert pending_adjustment.status_code == 201
    adjustment = pending_adjustment.json()
    assert adjustment["original_quantity"] == 240
    assert adjustment["review_status"] == "PENDING"
    assert client.post(f"/api/v1/claims/{claim_id}/adjustments/{adjustment['id']}/review?approve=true",
        headers=recycler, json={"decision": "Not authorized to review."}).status_code == 403
    approved_adjustment = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{adjustment['id']}/review?approve=true",
        headers=official, json={"decision": "Supporting weighbridge evidence matches."},
    )
    assert approved_adjustment.status_code == 200
    adjusted_claim = approved_adjustment.json()["claim"]
    assert adjusted_claim["mass_balance"]["processed_output_kg"] == 470
    assert adjusted_claim["original_mass_balance"]["processed_output_kg"] == 480
    assert adjusted_claim["mass_balance_adjustments"][0]["review_status"] == "APPROVED"
    assert adjusted_claim["audit_chain_valid"] is True
    approval_event = next(item for item in adjusted_claim["audit_events"]
                          if item["action_type"] == "MASS_BALANCE_ADJUSTMENT_APPROVED")
    assert approval_event["actor_user_id"] == "official-one"
    assert approval_event["actor_role"] == "GOVERNMENT_OFFICER"

    rejected_adjustment = client.post(f"/api/v1/claims/{claim_id}/adjustments", headers=recycler,
        json={"processing_batch_id": "batch-b", "field": "RESIDUAL_WASTE", "corrected_quantity": 25,
              "category": "DATA_ENTRY_CORRECTION", "reason": "Proposed residual correction."})
    assert rejected_adjustment.status_code == 201
    rejected = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{rejected_adjustment.json()['id']}/review?approve=false",
        headers=official, json={"decision": "Evidence does not support this change."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["claim"]["mass_balance"]["processed_output_kg"] == 470

    # Government sees the completed producer/recycler record and evidence trail.
    official_view = client.get(f"/api/v1/claims/{claim_id}", headers=official).json()
    assert official_view["mass_balance"]["declared_input_kg"] == 500
    assert official_view["mass_balance"]["received_input_kg"] == 492
    assert official_view["mass_balance"]["processed_output_kg"] == 470
    assert {item["source"] for item in official_view["evidence"]} == {"PRODUCER", "RECYCLER"}
    assert {item["category"] for item in official_view["evidence"]} == {
        "COLLECTION_WEIGHT_SLIP", "OTHER_SUPPORTING", "RECYCLER_RECEIPT",
        "PROCESSING_RECOVERY", "RECYCLING_CERTIFICATE",
    }
    assert next(item for item in official_view["evidence"] if item["category"] == "COLLECTION_WEIGHT_SLIP")["verification_status"] == "METADATA_CONSISTENT"

    # Government can record a routine audit without changing the claim decision state.
    assert client.post(
        f"/api/v1/claims/{claim_id}/audit-note",
        headers=producer_one,
        json={"audit_type": "ROUTINE", "note": "Producer cannot write audit records."},
    ).status_code == 403
    audit_before = official_view["status"]
    audited = client.post(
        f"/api/v1/claims/{claim_id}/audit-note",
        headers=official,
        json={"audit_type": "ROUTINE", "note": "Reviewed the evidence trail."},
    )
    assert audited.status_code == 200
    assert audited.json()["status"] == audit_before
    assert audited.json()["audit_history"][-1]["actor"]["role"] == "GOV_OFFICIAL"

    # Officer clarification returns the claim; correction appends history and recalculates totals.
    requested = client.post(f"/api/v1/claims/{claim_id}/clarification", headers=official,
                            json={"reason": "Please reconcile the second batch weighbridge amount."})
    assert requested.status_code == 200
    assert requested.json()["status"] == "AWAITING_CLARIFICATION"
    assert requested.json()["clarification_reason"].startswith("Please reconcile")
    corrected = client.post(
        f"/api/v1/claims/{claim_id}/processing", headers=recycler_coworker,
        json={"corrects_previous": True, "batches": [{"batch_id": "corrected-batch",
              "processed_output_kg": 470,
              "recovered_materials": [{"material": "Copper", "quantity_kg": 420}],
              "residual_waste_kg": 50, "processing_date": "2026-10-10"}]},
    )
    assert corrected.status_code == 200
    assert corrected.json()["mass_balance"]["declared_input_kg"] == 500
    assert corrected.json()["mass_balance"]["processed_output_kg"] == 470
    assert corrected.json()["processing_batches"][0]["batch_id"] == "corrected-batch"
    assert "CLAIM_APPROVED" not in {event["action"] for event in corrected.json()["audit_history"]}
    assert "PROCESSING_BATCH_CORRECTED" in {event["action"] for event in corrected.json()["audit_history"]}

    # Producers cannot use government-only workflow actions; officials can access all claims.
    assert client.post(
        f"/api/v1/claims/{claim_id}/approve",
        json={"official_name": "Producer"},
        headers=producer_one,
    ).status_code == 403
    assert client.get(f"/api/v1/claims/{claim_id}", headers=official).status_code == 200
    official_page = client.get("/api/v1/claims/?page=1&page_size=1", headers=official).json()
    assert len(official_page["items"]) == 1
    assert official_page["total"] == 2 and official_page["pages"] == 2
    second_page = client.get("/api/v1/claims/?page=2&page_size=1", headers=official).json()
    assert len(second_page["items"]) == 1
    assert official_page["items"][0]["id"] != second_page["items"][0]["id"]
    outside_payload = {**payload, "origin_lat": 25.0, "origin_lng": 90.0}
    outside_claim = client.post("/api/v1/claims/", json=outside_payload, headers=producer_one)
    assert outside_claim.status_code == 201
    assert outside_claim.json()["jurisdiction_id"] is None
    assert client.get(f"/api/v1/claims/{outside_claim.json()['id']}", headers=official).status_code == 404
    assert client.get(f"/api/v1/claims/{outside_claim.json()['id']}/audit", headers=official).status_code == 404
    assert client.post(f"/api/v1/claims/{outside_claim.json()['id']}/audit-note", headers=official,
                       json={"audit_type": "INVESTIGATION", "note": "Outside assigned area"}).status_code == 404
    assert client.post(
        f"/api/v1/claims/{claim_id}/approve",
        json={"official_name": "Official"},
        headers=official,
    ).json()["status"] == "APPROVED"
    approved_detail = client.get(f"/api/v1/claims/{claim_id}", headers=official).json()
    assert approved_detail["audit_history"][-1]["action"] == "CLAIM_APPROVED"
    assert approved_detail["audit_history"][-1]["actor"]["role"] == "GOV_OFFICIAL"
    engine.dispose()
