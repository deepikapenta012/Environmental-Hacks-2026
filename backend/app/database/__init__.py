"""
SQLAlchemy database setup for local development (SQLite).
"""

import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

logger = logging.getLogger("chainguard")

settings = get_settings()

# SQLite needs check_same_thread=False for FastAPI's threaded request handling
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args.update({"check_same_thread": False, "timeout": 30})

engine = create_engine(settings.database_url, connect_args=connect_args)
if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_mass_balance_details_column(target_engine=None) -> None:
    """Add the optional mass-balance JSON column to an existing local database."""
    target_engine = target_engine or engine
    columns = {column["name"] for column in inspect(target_engine).get_columns("claims")}
    if "mass_balance_details" not in columns:
        with target_engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE claims ADD COLUMN mass_balance_details JSON"
            ))


def ensure_auth_columns(target_engine=None) -> None:
    """Add auth fields to existing local databases without requiring Alembic."""
    target_engine = target_engine or engine
    inspector = inspect(target_engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    claim_columns = {column["name"] for column in inspector.get_columns("claims")}
    with target_engine.begin() as connection:
        if "password_salt" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN password_salt VARCHAR(32) NOT NULL DEFAULT ''"))
        if "owner_user_id" not in claim_columns:
            connection.execute(text("ALTER TABLE claims ADD COLUMN owner_user_id VARCHAR(50)"))
    with target_engine.begin() as connection:
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_claims_owner_user_id ON claims (owner_user_id)"))


def ensure_evidence_extracted_data_column(target_engine=None) -> None:
    """Add local structured-document data to existing evidence tables."""
    target_engine = target_engine or engine
    columns = {column["name"] for column in inspect(target_engine).get_columns("evidence")}
    if "extracted_data" not in columns:
        with target_engine.begin() as connection:
            connection.execute(text("ALTER TABLE evidence ADD COLUMN extracted_data JSON"))


def ensure_party_workflow_columns(target_engine=None) -> None:
    """Add recycler workflow and evidence ownership fields to existing databases."""
    target_engine = target_engine or engine
    inspector = inspect(target_engine)
    claim_columns = {column["name"] for column in inspector.get_columns("claims")}
    evidence_columns = {column["name"] for column in inspector.get_columns("evidence")}
    claim_additions = {
        "recycler_user_id": "VARCHAR(50)",
        "received_at": "DATETIME",
        "processing_date": "VARCHAR(20)",
        "processing_completed_at": "DATETIME",
        "clarification_reason": "TEXT",
        "recycler_notes": "TEXT",
    }
    evidence_additions = {
        "category": "VARCHAR(40) NOT NULL DEFAULT 'OTHER_SUPPORTING'",
        "uploaded_by_user_id": "VARCHAR(50)",
        "verification_status": "VARCHAR(20) NOT NULL DEFAULT 'MANUAL_REVIEW'",
    }
    with target_engine.begin() as connection:
        for name, column_type in claim_additions.items():
            if name not in claim_columns:
                connection.execute(text(f"ALTER TABLE claims ADD COLUMN {name} {column_type}"))
        if "source" not in evidence_columns:
            connection.execute(text(
                "ALTER TABLE evidence ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'PRODUCER'"
            ))
        for name, column_type in evidence_additions.items():
            if name not in evidence_columns:
                connection.execute(text(f"ALTER TABLE evidence ADD COLUMN {name} {column_type}"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_evidence_uploaded_by_user_id ON evidence (uploaded_by_user_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_claims_recycler_user_id ON claims (recycler_user_id)"
        ))
        if target_engine.dialect.name == "postgresql":
            connection.execute(text(
                "ALTER TABLE claims ALTER COLUMN status TYPE VARCHAR(40)"
            ))


def ensure_authorization_columns(target_engine=None) -> None:
    """Add explicit role and stable authorization references to existing databases.

    Legacy USER accounts are conservatively migrated to PRODUCER. Existing recycler
    name/user associations are intentionally not converted into verified memberships.
    """
    target_engine = target_engine or engine
    inspector = inspect(target_engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    claim_columns = {column["name"] for column in inspector.get_columns("claims")}
    jurisdiction_columns = {column["name"] for column in inspector.get_columns("government_jurisdictions")}
    facility_columns = {column["name"] for column in inspector.get_columns("recycler_facilities")}
    with target_engine.begin() as connection:
        if "role" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(30) NOT NULL DEFAULT 'PRODUCER'"))
            connection.execute(text("UPDATE users SET role = 'GOVERNMENT_OFFICER' WHERE persona = 'GOV_OFFICIAL'"))
        if "is_active" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        if "recycler_facility_id" not in claim_columns:
            connection.execute(text("ALTER TABLE claims ADD COLUMN recycler_facility_id VARCHAR(50)"))
        if "jurisdiction_id" not in claim_columns:
            connection.execute(text("ALTER TABLE claims ADD COLUMN jurisdiction_id VARCHAR(50)"))
        if "legacy_audit_migrated" not in claim_columns:
            connection.execute(text("ALTER TABLE claims ADD COLUMN legacy_audit_migrated BOOLEAN NOT NULL DEFAULT 0"))
        if "boundary" not in jurisdiction_columns:
            connection.execute(text("ALTER TABLE government_jurisdictions ADD COLUMN boundary JSON"))
        if "authorization_status" not in facility_columns:
            connection.execute(text("ALTER TABLE recycler_facilities ADD COLUMN authorization_status VARCHAR(30) NOT NULL DEFAULT 'PENDING'"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_role ON users (role)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_claims_recycler_facility_id ON claims (recycler_facility_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_claims_jurisdiction_id ON claims (jurisdiction_id)"))
        unmapped_facilities = connection.execute(text(
            "SELECT count(*) FROM claims WHERE recycler_user_id IS NOT NULL AND recycler_facility_id IS NULL"
        )).scalar_one()
        unmapped_jurisdictions = connection.execute(text(
            "SELECT count(*) FROM claims WHERE jurisdiction_id IS NULL"
        )).scalar_one()
    if unmapped_facilities or unmapped_jurisdictions:
        logger.warning("legacy authorization references need review", extra={
            "unmapped_facilities": unmapped_facilities,
            "unmapped_jurisdictions": unmapped_jurisdictions,
        })


def ensure_audit_event_guards(target_engine=None) -> None:
    """Install database-level update/delete guards for the append-only event table."""
    target_engine = target_engine or engine
    if target_engine.dialect.name == "sqlite":
        with target_engine.begin() as connection:
            connection.execute(text("""CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"""))
            connection.execute(text("""CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END"""))
            connection.execute(text("""CREATE TRIGGER IF NOT EXISTS admin_audit_events_no_update
                BEFORE UPDATE ON admin_audit_events BEGIN SELECT RAISE(ABORT, 'admin audit events are append-only'); END"""))
            connection.execute(text("""CREATE TRIGGER IF NOT EXISTS admin_audit_events_no_delete
                BEFORE DELETE ON admin_audit_events BEGIN SELECT RAISE(ABORT, 'admin audit events are append-only'); END"""))
    elif target_engine.dialect.name == "postgresql":
        with target_engine.begin() as connection:
            connection.execute(text("""CREATE OR REPLACE FUNCTION reject_audit_event_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'audit events are append-only'; END; $$"""))
            connection.execute(text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'audit_events_no_mutation'
                               AND tgrelid = 'audit_events'::regclass) THEN
                  EXECUTE 'CREATE TRIGGER audit_events_no_mutation BEFORE UPDATE OR DELETE ON audit_events
                  FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()';
                END IF; END $$"""))
            connection.execute(text("""CREATE OR REPLACE FUNCTION reject_admin_audit_event_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'admin audit events are append-only'; END; $$"""))
            connection.execute(text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'admin_audit_events_no_mutation'
                               AND tgrelid = 'admin_audit_events'::regclass) THEN
                  EXECUTE 'CREATE TRIGGER admin_audit_events_no_mutation BEFORE UPDATE OR DELETE ON admin_audit_events
                  FOR EACH ROW EXECUTE FUNCTION reject_admin_audit_event_mutation()';
                END IF; END $$"""))


def ensure_evidence_versioning_columns(target_engine=None) -> None:
    """Add evidence versioning and secure storage columns to existing databases."""
    target_engine = target_engine or engine
    inspector = inspect(target_engine)
    evidence_columns = {column["name"] for column in inspector.get_columns("evidence")}
    evidence_versioning_additions = {
        "logical_id": "VARCHAR(50) NOT NULL DEFAULT ''",
        "storage_key": "VARCHAR(1000) NOT NULL DEFAULT ''",
        "mime_type": "VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream'",
        "uploader_role": "VARCHAR(30) NOT NULL DEFAULT 'PRODUCER'",
        "status": "VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'",
        "version_number": "INTEGER NOT NULL DEFAULT 1",
        "replaced_by_id": "VARCHAR(50)",
        "replacement_reason": "TEXT",
        "linked_entity_type": "VARCHAR(50)",
        "linked_entity_id": "VARCHAR(100)",
        "extraction_provenance": "JSON",
    }
    with target_engine.begin() as connection:
        for name, column_type in evidence_versioning_additions.items():
            if name not in evidence_columns:
                connection.execute(text(f"ALTER TABLE evidence ADD COLUMN {name} {column_type}"))
        # Backfill logical_id from id where empty
        connection.execute(text("UPDATE evidence SET logical_id = id WHERE logical_id = '' OR logical_id IS NULL"))
        # Backfill storage_key from file_path where empty
        connection.execute(text("UPDATE evidence SET storage_key = file_path WHERE storage_key = '' OR storage_key IS NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_evidence_logical_id ON evidence (logical_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_evidence_status ON evidence (status)"))
    # Create evidence_versions table if not present
    table_names = inspector.get_table_names()
    if "evidence_versions" not in table_names:
        from app.models import EvidenceVersion  # noqa: F811
        EvidenceVersion.__table__.create(bind=target_engine, checkfirst=True)
    else:
        version_columns = {column["name"] for column in inspect(target_engine).get_columns("evidence_versions")}
        if "extraction_provenance" not in version_columns:
            with target_engine.begin() as connection:
                connection.execute(text("ALTER TABLE evidence_versions ADD COLUMN extraction_provenance JSON"))


def _apply_schema_0001(target_engine) -> None:
    """Adopt legacy databases and add current additive columns safely on retry."""
    ensure_mass_balance_details_column(target_engine)
    ensure_auth_columns(target_engine)
    ensure_evidence_extracted_data_column(target_engine)
    ensure_party_workflow_columns(target_engine)
    ensure_authorization_columns(target_engine)
    ensure_audit_event_guards(target_engine)
    ensure_evidence_versioning_columns(target_engine)
    _seed_existing_claim_reference_counters(target_engine)
    _report_legacy_orphans(target_engine)


def _apply_query_indexes_0002(target_engine) -> None:
    """Index common scoped, status-filtered claim lists for existing databases."""
    statements = (
        "CREATE INDEX IF NOT EXISTS ix_claims_owner_status_submitted ON claims (owner_user_id, status, submitted_at)",
        "CREATE INDEX IF NOT EXISTS ix_claims_facility_status_submitted ON claims (recycler_facility_id, status, submitted_at)",
        "CREATE INDEX IF NOT EXISTS ix_claims_jurisdiction_status_submitted ON claims (jurisdiction_id, status, submitted_at)",
    )
    with target_engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _seed_existing_claim_reference_counters(target_engine) -> None:
    import re
    from sqlalchemy.orm import Session
    from app.models import Claim, ClaimReferenceCounter

    maxima: dict[int, int] = {}
    with Session(target_engine) as db:
        for reference in db.query(Claim.reference_number).all():
            match = re.fullmatch(r"EWC-(\d{4})-(\d+)", reference[0] or "")
            if match:
                year, value = int(match.group(1)), int(match.group(2))
                maxima[year] = max(maxima.get(year, 0), value)
        for year, value in maxima.items():
            counter = db.get(ClaimReferenceCounter, year)
            if counter is None:
                db.add(ClaimReferenceCounter(year=year, value=value))
            elif counter.value < value:
                counter.value = value
        db.commit()


def _report_legacy_orphans(target_engine) -> None:
    """Report invalid legacy references without guessing or rewriting mappings."""
    checks = {
        "claim owners": "SELECT count(*) FROM claims c LEFT JOIN users u ON u.id=c.owner_user_id WHERE c.owner_user_id IS NOT NULL AND u.id IS NULL",
        "claim facilities": "SELECT count(*) FROM claims c LEFT JOIN recycler_facilities f ON f.id=c.recycler_facility_id WHERE c.recycler_facility_id IS NOT NULL AND f.id IS NULL",
        "claim jurisdictions": "SELECT count(*) FROM claims c LEFT JOIN government_jurisdictions j ON j.id=c.jurisdiction_id WHERE c.jurisdiction_id IS NOT NULL AND j.id IS NULL",
        "facility memberships": "SELECT count(*) FROM facility_memberships m LEFT JOIN users u ON u.id=m.user_id LEFT JOIN recycler_facilities f ON f.id=m.facility_id WHERE u.id IS NULL OR f.id IS NULL",
        "officer assignments": "SELECT count(*) FROM government_jurisdiction_assignments a LEFT JOIN users u ON u.id=a.user_id LEFT JOIN government_jurisdictions j ON j.id=a.jurisdiction_id WHERE u.id IS NULL OR j.id IS NULL",
    }
    with target_engine.connect() as connection:
        invalid = {label: connection.execute(text(query)).scalar_one() for label, query in checks.items()}
    invalid = {label: count for label, count in invalid.items() if count}
    if invalid:
        logger.warning("invalid historical references require review", extra={"reference_counts": invalid})


MIGRATIONS = (
    ("0001_legacy_schema_adoption", _apply_schema_0001),
    ("0002_scoped_claim_list_indexes", _apply_query_indexes_0002),
)


def run_migrations(target_engine=None) -> None:
    """Apply ordered additive migrations; interrupted steps are safe to retry.

    A new version must be added to this registry for future schema changes.
    The legacy migration is idempotent and records completion only after all
    compatibility DDL and backfills have succeeded.
    """
    target_engine = target_engine or engine
    with target_engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(40) NOT NULL)"))
        applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}

    for version, upgrade in MIGRATIONS:
        if version in applied:
            continue
        upgrade(target_engine)
        with target_engine.begin() as connection:
            connection.execute(text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, CURRENT_TIMESTAMP)"),
                               {"version": version})


def get_db():
    """FastAPI dependency that provides a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

