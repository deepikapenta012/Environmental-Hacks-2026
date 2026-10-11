from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import Base, MIGRATIONS, run_migrations
import app.models  # noqa: F401


def test_fresh_database_migration_registry_is_idempotent(tmp_path):
    database = create_engine(f"sqlite:///{tmp_path / 'migration-test.db'}")
    Base.metadata.create_all(database)
    expected_versions = [version for version, _upgrade in MIGRATIONS]
    assert expected_versions == [
        "0001_legacy_schema_adoption",
        "0002_scoped_claim_list_indexes",
    ]
    run_migrations(database)
    # Keep a real claim in place across the second migration pass as well.
    from app.models import Claim
    with Session(database) as session:
        session.add(Claim(
            id="migration-survivor", reference_number="EWC-2026-09001", status="PENDING",
            producer_name="Preserved producer", producer_registration_number="PR-KEEP",
            recycler_name="Preserved recycler", recycler_registration_number="RC-KEEP",
            waste_category="WEEE", declared_weight_kg=1, collection_date="2026-01-01",
        ))
        session.commit()
    run_migrations(database)
    with database.connect() as connection:
        versions = connection.execute(text("SELECT version FROM schema_migrations")).scalars().all()
        indexes = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
    assert versions == expected_versions
    assert versions.count("0001_legacy_schema_adoption") == 1
    assert versions.count("0002_scoped_claim_list_indexes") == 1
    assert "ix_claims_jurisdiction_status_submitted" in indexes
    with Session(database) as session:
        assert session.get(Claim, "migration-survivor").producer_name == "Preserved producer"
    database.dispose()


def test_migration_seeds_reference_counter_from_legacy_claims(tmp_path):
    database = create_engine(f"sqlite:///{tmp_path / 'reference-test.db'}")
    Base.metadata.create_all(database)
    from app.models import Claim, ClaimReferenceCounter
    with Session(database) as session:
        session.add(Claim(
            id="claim-legacy", reference_number="EWC-2026-08637", status="PENDING",
            producer_name="Legacy producer", producer_registration_number="PR-1",
            recycler_name="Legacy recycler", recycler_registration_number="RC-1",
            waste_category="WEEE", declared_weight_kg=1, collection_date="2026-01-01",
        ))
        session.commit()
    run_migrations(database)
    with Session(database) as session:
        assert session.get(ClaimReferenceCounter, 2026).value == 8637
    database.dispose()
