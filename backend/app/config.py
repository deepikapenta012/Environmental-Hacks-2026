from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./ewaste_chainguard.db"
    api_v1_prefix: str = "/api/v1"
    project_name: str = "E-Waste ChainGuard"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    environment: str = "development"
    max_request_body_bytes: int = 12 * 1024 * 1024
    login_attempt_limit: int = 10
    login_attempt_window_seconds: int = 300

    # Verification engine
    verification_model_version: str = "risk-engine-v3.0.0"
    verification_ruleset_version: str = "risk-rules-v3.0.0"
    risk_rule_weights_json: str = "{}"
    risk_group_caps_json: str = '{"MASS_BALANCE":30,"TRANSPORT":30,"DOCUMENT_CONSISTENCY":30,"EVIDENCE_INTEGRITY":30,"DUPLICATE":35,"COMPLETENESS":0}'
    risk_band_low_max: int = 25
    risk_band_medium_max: int = 50
    risk_band_high_max: int = 75
    max_hgv_speed_kmh: float = 90.0
    mass_balance_tolerance_pct: float = 5.0
    phash_duplicate_threshold: float = 0.90
    duplicate_claim_similarity_threshold_pct: float = 80.0
    duplicate_claim_quantity_tolerance_pct: float = 2.0
    duplicate_claim_date_window_days: int = 3
    duplicate_claim_risk_contribution: int = 30
    document_quantity_tolerance_pct: float = 5.0
    document_date_tolerance_days: int = 3
    document_mismatch_risk_contribution: int = 12
    duplicate_document_identifier_risk_contribution: int = 28
    geocoding_search_url: str = "https://nominatim.openstreetmap.org/search"
    jwt_secret_key: str = ""
    access_token_minutes: int = 30
    bootstrap_users_json: str = ""
    bootstrap_facilities_json: str = ""
    bootstrap_memberships_json: str = ""
    bootstrap_jurisdictions_json: str = ""

    # Secure evidence storage
    evidence_storage_root: str = "./evidence_store"
    evidence_max_file_size: int = 10 * 1024 * 1024  # 10 MB
    evidence_storage_backend: str = "local"
    evidence_s3_bucket: str = ""
    evidence_s3_prefix: str = "chainguard/evidence"
    evidence_s3_kms_key_id: str = ""
    aws_region: str = "ap-south-1"

    # OpenTelemetry exports to an AWS Distro for OpenTelemetry Collector when enabled.
    otel_enabled: bool = False
    otel_service_name: str = "ewaste-chainguard-api"
    otel_collector_endpoint: str = "http://127.0.0.1:4317"
    otel_insecure: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
