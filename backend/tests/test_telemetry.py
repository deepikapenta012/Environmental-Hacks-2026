from io import StringIO
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.services.telemetry import configure_telemetry, flush_telemetry


def _settings(**overrides):
    values = {
        "otel_enabled": True,
        "otel_service_name": "chainguard-test",
        "otel_trace_sample_rate": 1.0,
        "otel_metric_export_interval_millis": 10000,
        "environment": "test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_telemetry_is_noop_when_disabled():
    settings = _settings(otel_enabled=False)

    assert configure_telemetry(object(), settings, object()) is False


def test_fastapi_and_sqlalchemy_export_sanitized_console_traces(monkeypatch):
    output = StringIO()
    database = create_engine("sqlite://", connect_args={"check_same_thread": False})
    app = FastAPI()

    @app.get("/claims/{claim_id}")
    def read_claim(claim_id: str):
        with database.connect() as connection:
            return {"result": connection.execute(
                text("SELECT :value"), {"value": "private-sql-value"}
            ).scalar_one()}

    @app.get("/failure/{claim_id}")
    def fail_claim(claim_id: str):
        raise RuntimeError("private-exception-message")

    @app.post("/claims/{claim_id}")
    def read_claim_with_sensitive_body(claim_id: str, payload: dict):
        return {"accepted": bool(payload)}

    settings = _settings()
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST", "authorization,cookie,x-api-key")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE", "*")
    assert configure_telemetry(app, settings, database, console_stream=output) is True
    # Repeated startup/configuration for the same objects must not add middleware
    # or SQLAlchemy event listeners more than once.
    assert configure_telemetry(app, settings, database, console_stream=output) is True

    with TestClient(app) as client:
        response = client.get("/claims/route-secret?password=query-secret", headers={
            "authorization": "Bearer jwt-secret",
            "cookie": "session=cookie-secret",
            "x-api-key": "api-key-secret",
        })
        assert response.status_code == 200
        body_response = client.post(
            "/claims/body-secret?password=query-secret",
            json={"password": "body-secret", "evidence": "private-evidence-content"},
            headers={"authorization": "Bearer jwt-secret", "cookie": "session=cookie-secret", "x-api-key": "api-key-secret"},
        )
        assert body_response.status_code == 200
    with TestClient(app, raise_server_exceptions=False) as error_client:
        assert error_client.get("/failure/another-secret?token=token-secret").status_code == 500

    flush_telemetry()
    database.dispose()
    exported = output.getvalue()

    assert "GET /claims/{claim_id}" in exported
    assert exported.count('"name": "GET /claims/{claim_id}"') == 1
    assert exported.count('"name": "SELECT"') == 1
    assert "RuntimeError" in exported
    assert "SELECT" in exported or "Database operation" in exported
    assert "http.server" in exported
    assert "private-sql-value" not in exported
    assert "private-exception-message" not in exported
    assert "route-secret" not in exported
    assert "query-secret" not in exported
    assert "jwt-secret" not in exported
    assert "cookie-secret" not in exported
    assert "api-key-secret" not in exported
    assert "token-secret" not in exported
    assert "body-secret" not in exported
    assert "private-evidence-content" not in exported
