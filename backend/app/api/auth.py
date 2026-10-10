"""Database-backed login and current-user endpoints."""

from datetime import datetime, timezone
from collections import defaultdict, deque
from threading import Lock
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import create_access_token, verify_password
from app.database import get_db
from app.models import FacilityMembership, RecyclerFacility, User

router = APIRouter(prefix="/auth", tags=["Authentication"])
_login_attempts: dict[str, deque[float]] = defaultdict(deque)
_login_attempts_lock = Lock()


def _check_login_rate_limit(key: str, *, now: float, limit: int, window: int) -> None:
    with _login_attempts_lock:
        attempts = _login_attempts[key]
        while attempts and now - attempts[0] >= window:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please wait and try again.",
                                headers={"Retry-After": str(max(1, int(window - (now - attempts[0]))) )})


def _record_login_failure(key: str, *, now: float, window: int) -> None:
    with _login_attempts_lock:
        attempts = _login_attempts[key]
        while attempts and now - attempts[0] >= window:
            attempts.popleft()
        attempts.append(now)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


def user_response(user: User, db: Session) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "organisation": user.organisation,
        "persona": user.persona,
        "role": user.role,
        "is_active": user.is_active,
        "facility_ids": [row[0] for row in db.query(FacilityMembership.facility_id)
            .join(RecyclerFacility, RecyclerFacility.id == FacilityMembership.facility_id)
            .filter(FacilityMembership.user_id == user.id, FacilityMembership.active.is_(True),
                    FacilityMembership.verified.is_(True), RecyclerFacility.authorization_status == "AUTHORIZED")
            .all()] if user.role == "RECYCLER_EMPLOYEE" else [],
        "department": user.department,
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    from app.config import get_settings
    settings = get_settings()
    client_key = request.client.host if request.client else "unknown"
    keys = (f"ip:{client_key}", f"account:{body.username.strip().lower()}")
    now = time.monotonic()
    for key in keys:
        _check_login_rate_limit(key, now=now, limit=settings.login_attempt_limit,
                                window=settings.login_attempt_window_seconds)
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if user is None or not user.is_active or not verify_password(body.password, user):
        for key in keys:
            _record_login_failure(key, now=time.monotonic(), window=settings.login_attempt_window_seconds)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    with _login_attempts_lock:
        for key in keys:
            _login_attempts.pop(key, None)
    token, expires_at = create_access_token(user)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
        "user": user_response(user, db),
    }
