import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import _check_login_rate_limit, _record_login_failure, _login_attempts


def test_login_attempt_limit_blocks_until_window_expires():
    key = "test-login-throttle"
    _login_attempts.pop(key, None)
    _record_login_failure(key, now=100.0, window=60)
    _record_login_failure(key, now=101.0, window=60)
    with pytest.raises(HTTPException) as raised:
        _check_login_rate_limit(key, now=102.0, limit=2, window=60)
    assert raised.value.status_code == 429
    _check_login_rate_limit(key, now=161.0, limit=2, window=60)
    _login_attempts.pop(key, None)


def test_request_body_limit_rejects_chunked_and_declared_oversize_payloads():
    from app.main import RequestBodyLimitMiddleware
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=4)

    @app.post("/body")
    async def body(payload: dict):
        return {"ok": True}

    client = TestClient(app)
    assert client.post("/body", content=b'{"x":1}').status_code == 413
    assert client.post("/body", json={}).status_code == 200


@pytest.mark.parametrize("origin", [
    "*", "http://chainguard.example", "https://localhost:5173",
    "https://app.localhost", "https://chainguard.example/path", "https://*.example.com",
    " https://chainguard.example",
])
def test_production_cors_rejects_nonproduction_origins(origin):
    from app.main import validate_production_cors_origins

    with pytest.raises(RuntimeError):
        validate_production_cors_origins([origin])


def test_production_cors_accepts_exact_https_origin():
    from app.main import validate_production_cors_origins

    validate_production_cors_origins(["https://chainguard.example", "https://admin.chainguard.example:8443"])
    with pytest.raises(RuntimeError):
        validate_production_cors_origins([])


def test_health_readiness_checks_database_and_liveness_stays_available(monkeypatch):
    from app import main

    class FakeResult:
        def scalar_one(self):
            return 1

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return FakeResult()

    class ReadyEngine:
        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(main, "engine", ReadyEngine())
    client = TestClient(main.app)
    assert client.get("/health/ready").json() == {
        "status": "ready", "dependencies": {"database": "ready"}
    }
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health").json() == {"status": "healthy"}

    class UnavailableEngine:
        def connect(self):
            raise OSError("database unavailable")

    monkeypatch.setattr(main, "engine", UnavailableEngine())
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "Service is not ready"
