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
