from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import api_router
from app.auth import create_access_token, hash_password
from app.database import Base, get_db
from app.models import (AdminAuditEvent, AuditEvent, Claim, FacilityMembership,
                        GovernmentJurisdiction, GovernmentJurisdictionAssignment,
                        RecyclerFacility, User)


def test_authorization_schema_upgrade_can_be_retried(monkeypatch):
    from app import database
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id VARCHAR(50) PRIMARY KEY, persona VARCHAR(20) NOT NULL)"))
        connection.execute(text("CREATE TABLE claims (id VARCHAR(50) PRIMARY KEY, recycler_user_id VARCHAR(50))"))
        connection.execute(text("CREATE TABLE government_jurisdictions (id VARCHAR(50) PRIMARY KEY, name VARCHAR(200) NOT NULL)"))
        connection.execute(text("CREATE TABLE recycler_facilities (id VARCHAR(50) PRIMARY KEY)"))
    monkeypatch.setattr(database, "engine", engine)
    database.ensure_authorization_columns()
    database.ensure_authorization_columns()
    assert {c["name"] for c in inspect(engine).get_columns("users")} >= {"role", "is_active"}
    assert {c["name"] for c in inspect(engine).get_columns("claims")} >= {"recycler_facility_id", "jurisdiction_id", "legacy_audit_migrated"}
    assert "authorization_status" in {c["name"] for c in inspect(engine).get_columns("recycler_facilities")}
    engine.dispose()


def test_admin_provisioning_and_legacy_review(monkeypatch):
    from app import auth
    from app.config import Settings
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(jwt_secret_key="test-only-secret-key-with-32-chars"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    password_hash, salt = hash_password("correct-horse-battery")
    with factory() as db:
        for uid, role in (("admin", "ADMINISTRATOR"), ("producer", "PRODUCER"),
                          ("worker", "RECYCLER_EMPLOYEE"), ("officer", "GOVERNMENT_OFFICER")):
            db.add(User(id=uid, username=uid, password_hash=password_hash, password_salt=salt,
                        display_name=uid, organisation="Test Org", persona="USER", role=role))
        db.add(RecyclerFacility(id="facility", name="Recycler", registration_number="R-1",
            address="Old", authorization_status="AUTHORIZED", permitted_waste_categories=["WEEE Category 1"]))
        db.add(GovernmentJurisdiction(id="area", name="Area", boundary=[[0, 0], [2, 0], [2, 2]]))
        db.add(Claim(id="legacy-claim", owner_user_id="producer", reference_number="EWC-LEGACY",
            status="AWAITING_RECYCLER_CONFIRMATION", producer_name="Producer",
            producer_registration_number="P-1", recycler_name="Legacy recycler",
            recycler_registration_number="R-1", waste_category="WEEE Category 1", declared_weight_kg=10,
            received_weight_kg=0, processed_output_kg=0, collection_date="2026-01-01",
            origin_address="Origin", destination_address="Destination", mass_balance_details={"audit_history": []}))
        db.commit()

    app = FastAPI()
    app.include_router(api_router)
    def override_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    with factory() as db:
        admin_token, _ = create_access_token(db.get(User, "admin"))
        producer_token, _ = create_access_token(db.get(User, "producer"))
        worker_token, _ = create_access_token(db.get(User, "worker"))
        officer_token, _ = create_access_token(db.get(User, "officer"))
    admin = {"Authorization": f"Bearer {admin_token}"}
    producer = {"Authorization": f"Bearer {producer_token}"}
    worker = {"Authorization": f"Bearer {worker_token}"}
    officer = {"Authorization": f"Bearer {officer_token}"}

    assert client.get("/api/v1/admin/facilities", headers=producer).status_code == 403
    assert client.get("/api/v1/admin/accounts", headers=officer).status_code == 403
    assert client.post("/api/v1/admin/accounts/producer/role", headers=admin,
        json={"role": "ADMINISTRATOR", "reason": "Role creation is disabled"}).status_code == 404
    assert client.post("/api/v1/admin/facilities", headers=worker, json={
        "name": "New", "registration_number": "R-2", "authorization_status": "AUTHORIZED",
        "permitted_waste_categories": ["WEEE Category 1"], "reason": "Verified registry record",
    }).status_code == 403

    created = client.post("/api/v1/admin/facilities", headers=admin, json={
        "name": "Verified Recycler", "registration_number": "R-2", "authorization_status": "AUTHORIZED",
        "permitted_waste_categories": ["WEEE Category 1"], "reason": "Authorization document checked",
    })
    assert created.status_code == 201
    facility_id = created.json()["id"]
    assert client.post(f"/api/v1/admin/facilities/{facility_id}/members/worker", headers=admin,
        json={"active": True, "verified": True, "reason": "Identity verified against employer"}).status_code == 200
    assert client.post("/api/v1/admin/jurisdictions/area", headers=admin, json={
        "name": "Area", "boundary": [[0, 0], [2, 0], [2, 2]], "reason": "Boundary confirmed by registry",
    }).status_code == 200
    assert client.post("/api/v1/admin/jurisdictions/area/officers/officer", headers=admin,
        json={"reason": "Officer appointment confirmed"}).status_code == 200
    assert client.post("/api/v1/admin/jurisdictions/area/officers/worker", headers=admin,
        json={"reason": "Invalid role should be rejected"}).status_code == 422

    unresolved = client.get("/api/v1/admin/legacy", headers=admin).json()
    assert unresolved["claims"][0]["id"] == "legacy-claim"
    assert not unresolved["recycler_accounts"]
    no_confirm = client.post("/api/v1/admin/legacy/claims/legacy-claim/resolve", headers=admin,
        json={"recycler_facility_id": facility_id, "jurisdiction_id": "area",
              "reason": "Mappings verified against files", "confirm": False})
    assert no_confirm.status_code == 400
    resolved = client.post("/api/v1/admin/legacy/claims/legacy-claim/resolve", headers=admin,
        json={"recycler_facility_id": facility_id, "jurisdiction_id": "area",
              "reason": "Mappings verified against registry evidence", "confirm": True})
    assert resolved.status_code == 200
    assert client.get("/api/v1/claims/legacy-claim", headers=admin).status_code == 404
    assert client.get("/api/v1/claims/assigned", headers=worker).json()[0]["id"] == "legacy-claim"
    assert client.post("/api/v1/admin/legacy/claims/legacy-claim/resolve", headers=admin,
        json={"recycler_facility_id": facility_id, "jurisdiction_id": "area",
              "reason": "Retry after client timeout", "confirm": True}).status_code == 200
    assert client.get("/api/v1/admin/legacy", headers=admin).json() == {
        "claims": [], "recycler_accounts": [], "government_accounts": [],
    }
    assert client.post("/api/v1/admin/legacy/claims/legacy-claim/resolve", headers=producer,
        json={"jurisdiction_id": "area", "reason": "Should be denied", "confirm": True}).status_code == 403

    # Revocation takes effect while the existing bearer token is still valid.
    assert client.get("/api/v1/claims/assigned", headers=worker).status_code == 200
    assert client.post("/api/v1/admin/facilities", headers=admin, json={
        "id": facility_id, "name": "Verified Recycler", "registration_number": "R-2", "address": "",
        "authorization_status": "SUSPENDED", "permitted_waste_categories": ["WEEE Category 1"],
        "reason": "Authorization temporarily suspended",
    }).status_code == 201
    assert client.get("/api/v1/claims/assigned", headers=worker).json() == []
    assert client.post("/api/v1/admin/facilities", headers=admin, json={
        "id": facility_id, "name": "Verified Recycler", "registration_number": "R-2", "address": "",
        "authorization_status": "AUTHORIZED", "permitted_waste_categories": ["WEEE Category 1"],
        "reason": "Authorization reinstated",
    }).status_code == 201
    assert client.request("DELETE", f"/api/v1/admin/facilities/{facility_id}/members/worker", headers=admin,
        json={"reason": "Employee left the facility"}).status_code == 200
    assert client.get("/api/v1/claims/assigned", headers=worker).json() == []

    assert client.post("/api/v1/admin/accounts/worker/status?active=false", headers=admin,
        json={"reason": "Account holder access suspended"}).status_code == 200
    assert client.get("/api/v1/claims/assigned", headers=worker).status_code == 401
    with factory() as db:
        claim = db.get(Claim, "legacy-claim")
        assert claim.recycler_facility_id == facility_id and claim.jurisdiction_id == "area"
        assert claim.recycler_name == "Legacy recycler" and claim.recycler_registration_number == "R-1"
        assert db.query(AuditEvent).filter_by(claim_id=claim.id, action_type="ADMIN_LEGACY_MAPPING_RESOLVED").count() == 1
        assert db.query(AdminAuditEvent).count() >= 6
        assert db.query(FacilityMembership).filter_by(user_id="worker", facility_id=facility_id).one().active is False
        assert db.query(GovernmentJurisdictionAssignment).filter_by(user_id="officer", jurisdiction_id="area").count() == 1
    assert len(client.get("/api/v1/admin/activity", headers=admin).json()) >= 6
    engine.dispose()
