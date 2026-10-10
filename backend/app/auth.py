"""Small stdlib-only password and HS256 JWT helpers for local ChainGuard auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User

PRODUCER = "PRODUCER"
RECYCLER_EMPLOYEE = "RECYCLER_EMPLOYEE"
GOVERNMENT_OFFICER = "GOVERNMENT_OFFICER"
ADMINISTRATOR = "ADMINISTRATOR"
VALID_ROLES = {PRODUCER, RECYCLER_EMPLOYEE, GOVERNMENT_OFFICER, ADMINISTRATOR}

PASSWORD_ITERATIONS = 310_000
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PASSWORD_ITERATIONS
    ).hex()
    return digest, salt


def verify_password(password: str, user: User) -> bool:
    if not user.password_salt:
        return False
    digest, _ = hash_password(password, user.password_salt)
    return hmac.compare_digest(digest, user.password_hash)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def create_access_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise HTTPException(status_code=503, detail="JWT_SECRET_KEY must be configured with at least 32 characters")
    expires_at = int(time.time()) + settings.access_token_minutes * 60
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": user.id, "exp": expires_at}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(settings.jwt_secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}", expires_at


def decode_access_token(token: str) -> str:
    settings = get_settings()
    if len(settings.jwt_secret_key) < 32:
        raise HTTPException(status_code=401, detail="Access-token verification is not configured")
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(base64.urlsafe_b64decode(header_part + "=" * (-len(header_part) % 4)))
        payload = json.loads(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise ValueError("Unexpected JWT header")
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = _b64(hmac.new(settings.jwt_secret_key.encode(), signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature_part):
            raise ValueError("Invalid signature")
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError("Expired token")
        subject = payload["sub"]
        if not isinstance(subject, str) or not subject:
            raise ValueError("Missing subject")
        return subject
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is inactive")
    if user.role not in VALID_ROLES:
        raise HTTPException(status_code=403, detail="User role is not authorized")
    return user


def require_government_official(user: User = Depends(get_current_user)) -> User:
    if user.role != GOVERNMENT_OFFICER:
        raise HTTPException(status_code=403, detail="Government official role required")
    return user


def require_administrator(user: User = Depends(get_current_user)) -> User:
    if user.role != ADMINISTRATOR:
        raise HTTPException(status_code=403, detail="Administrator role required")
    return user


def require_producer(user: User = Depends(get_current_user)) -> User:
    if user.role != PRODUCER:
        raise HTTPException(status_code=403, detail="Producer role required")
    return user


def require_recycler_employee(user: User = Depends(get_current_user)) -> User:
    if user.role != RECYCLER_EMPLOYEE:
        raise HTTPException(status_code=403, detail="Recycler employee role required")
    return user
