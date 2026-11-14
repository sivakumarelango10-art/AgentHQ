from __future__ import annotations

import base64
import hmac
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from typing import Any
from uuid import uuid4

import argon2
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from . import db

# --- Argon2 Password Hasher ---
_password_hasher = argon2.PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    type=argon2.Type.ID,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2id hash in constant time."""
    if not plain_password or not hashed_password:
        return False
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, Exception):
        return False


# --- Configuration Resolvers ---

COOKIE_NAME = "studio_session"
FALLBACK_COOKIE_NAME = "agenthq_session"
SESSION_TTL_SECONDS = int(os.getenv("SESSION_EXPIRY_SECONDS", "86400"))  # 24 hours
WS_TICKET_TTL_SECONDS = int(os.getenv("WS_TICKET_EXPIRY_SECONDS", "60"))  # 60 seconds
LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "60"))


def get_owner_username() -> str:
    return (os.getenv("STUDIO_USERNAME") or os.getenv("OWNER_USERNAME") or "founder").strip()


def get_owner_password_hash() -> str:
    return (os.getenv("STUDIO_PASSWORD_HASH") or os.getenv("OWNER_PASSWORD_HASH") or "").strip()


def get_session_secret() -> str:
    secret = (os.getenv("SESSION_SECRET") or "").strip()
    if not secret:
        # For non-production development without explicit secret, use a stable fallback
        if os.getenv("ENVIRONMENT", "").strip().casefold() == "production":
            raise RuntimeError("SESSION_SECRET must be configured in production.")
        return "agenthq-default-dev-session-secret-min32bytes!"
    return secret


def get_runtime_api_token() -> str:
    return (os.getenv("RUNTIME_API_TOKEN") or "").strip()


def is_production() -> bool:
    return os.getenv("ENVIRONMENT", "").strip().casefold() == "production"


def is_auth_enforced() -> bool:
    """Check if runtime endpoint authentication is actively enforced."""
    if is_production():
        return True
    if get_runtime_api_token():
        return True
    if os.getenv("AUTH_ENFORCED", "").strip().casefold() in ("true", "1", "yes"):
        return True
    return False


def get_allowed_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "")
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


# --- Persistent Database-Backed Security State ---

# Backward-compatibility shims for legacy test harnesses
_session_lock = threading.Lock()
_active_sessions: dict[str, dict[str, Any]] = {}
_revoked_session_ids: set[str] = set()

_ticket_lock = threading.Lock()
_active_ws_tickets: dict[str, float] = {}
_consumed_ws_tickets: set[str] = set()

_rate_limit_lock = threading.Lock()
_login_failures: dict[str, list[float]] = {}


# --- Rate Limiting ---

def resolve_client_ip(request: Request) -> str:
    if os.getenv("TRUSTED_PROXY", "").strip() in ("1", "true"):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def check_login_rate_limit(ip: str) -> tuple[bool, int]:
    """Check if an IP is locked out using database-backed tracking."""
    return db.check_login_rate_limit(
        ip_address=ip,
        window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        max_attempts=LOGIN_MAX_FAILED_ATTEMPTS,
    )


def record_login_failure(ip: str, username: str | None = None) -> None:
    """Record a failed login attempt in the database."""
    db.record_login_attempt(ip_address=ip, username=username, success=False)


def reset_login_rate_limit(ip: str) -> None:
    """Reset failed login attempts for an IP in the database."""
    db.reset_login_rate_limit(ip_address=ip)


# --- Founder Authentication ---

def verify_founder_credentials(username: str, plain_password: str) -> bool:
    """Validate founder credentials against configured Argon2id hash."""
    expected_username = get_owner_username()
    expected_hash = get_owner_password_hash()

    if not expected_hash:
        # Without a configured password hash, founder login is disabled
        return False

    username_matches = secrets.compare_digest(
        (username or "").strip().casefold(),
        expected_username.casefold(),
    )
    password_valid = verify_password(plain_password, expected_hash)
    return username_matches and password_valid


# --- Cryptographic Signing & Session Management ---

def _sign_payload(payload_b64: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode("utf-8").rstrip("=")


def create_session(
    username: str,
    role: str = "founder",
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """
    Create a new database-backed session and return:
    (signed_session_cookie_token, csrf_token, session_data)
    """
    now = int(time.time())
    expires_at = now + SESSION_TTL_SECONDS
    session_id = uuid4().hex
    csrf_token = secrets.token_urlsafe(32)
    csrf_token_hash = hashlib.sha256(csrf_token.encode("utf-8")).hexdigest()

    data = {
        "session_id": session_id,
        "username": username,
        "role": role,
        "created_at": now,
        "expires_at": expires_at,
        "csrf_token": csrf_token,
    }

    payload_json = json.dumps(data, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    signature = _sign_payload(payload_b64, get_session_secret())
    signed_token = f"{payload_b64}.{signature}"
    session_token_hash = hashlib.sha256(signed_token.encode("utf-8")).hexdigest()

    db.create_owner_session(
        session_id=session_id,
        session_token_hash=session_token_hash,
        username=username,
        role=role,
        csrf_token_hash=csrf_token_hash,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return signed_token, csrf_token, data


def verify_session_token(token: str | None) -> dict[str, Any] | None:
    """Verify token signature, expiration, and database validity."""
    if not token or "." not in token:
        return None

    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    payload_b64, signature = parts

    secret = get_session_secret()
    expected_sig = _sign_payload(payload_b64, secret)
    if not secrets.compare_digest(signature, expected_sig):
        return None

    # Decode payload
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded)
        data = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    session_id = data.get("session_id")
    expires_at = data.get("expires_at", 0)
    now = int(time.time())

    if now > expires_at:
        return None

    # Authoritative check against persistent database
    record = db.get_owner_session(session_id)
    if not record:
        return None
    if record.get("is_revoked"):
        return None
    if record.get("expires_at", 0) < now:
        return None

    # Verify CSRF token hash match
    csrf_token = data.get("csrf_token")
    stored_csrf_hash = record.get("csrf_token_hash")
    if csrf_token and stored_csrf_hash:
        computed_hash = hashlib.sha256(csrf_token.encode("utf-8")).hexdigest()
        if not secrets.compare_digest(computed_hash, stored_csrf_hash):
            return None

    return data


def revoke_session(session_id: str | None) -> bool:
    """Revoke a session persistently in the database."""
    if not session_id:
        return False
    return db.revoke_owner_session(session_id)


# --- WebSocket Ticket Security ---

def create_ws_ticket(username: str) -> tuple[str, int]:
    """
    Generate a signed, short-lived single-use ticket for WebSocket connections,
    persisting its SHA-256 hash in the database.
    Returns (ticket_string, ttl_seconds).
    """
    now = int(time.time())
    expires_at = now + WS_TICKET_TTL_SECONDS
    ticket_id = uuid4().hex

    data = {
        "ticket_id": ticket_id,
        "username": username,
        "expires_at": expires_at,
    }

    payload_json = json.dumps(data, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    signature = _sign_payload(payload_b64, get_session_secret())
    ticket = f"{payload_b64}.{signature}"

    ticket_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    db.create_websocket_ticket(
        ticket_id=ticket_id,
        ticket_hash=ticket_hash,
        username=username,
        expires_at=expires_at,
    )

    return ticket, WS_TICKET_TTL_SECONDS


def verify_and_consume_ws_ticket(ticket: str | None) -> tuple[bool, str | None]:
    """
    Verify ticket signature, expiration, and enforce atomic single-use replay protection
    directly in the database.
    Returns (is_valid, username_or_reason).
    """
    if not ticket or "." not in ticket:
        return False, "Malformed ticket"

    parts = ticket.split(".", 1)
    if len(parts) != 2:
        return False, "Malformed ticket structure"
    payload_b64, signature = parts

    secret = get_session_secret()
    expected_sig = _sign_payload(payload_b64, secret)
    if not secrets.compare_digest(signature, expected_sig):
        return False, "Invalid signature"

    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded)
        data = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return False, "Invalid ticket payload"

    if not isinstance(data, dict):
        return False, "Invalid ticket format"

    expires_at = data.get("expires_at", 0)
    now = int(time.time())

    if now > expires_at:
        return False, "Ticket expired"

    ticket_hash = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
    success, username, reason = db.consume_websocket_ticket(ticket_hash)
    if not success:
        return False, reason or "Ticket verification failed"

    return True, username or data.get("username", "founder")


# --- Cookie Helpers ---

def set_session_cookie(response: Response, token: str) -> None:
    secure = is_production()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    secure = is_production()
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    response.delete_cookie(
        key=FALLBACK_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def extract_session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME) or request.cookies.get(FALLBACK_COOKIE_NAME)


# --- Dependencies for FastAPI ---

def get_current_session(request: Request) -> dict[str, Any] | None:
    token = extract_session_token(request)
    return verify_session_token(token)


def require_runtime_auth(request: Request) -> dict[str, Any]:
    """
    Authenticate runtime API requests.
    Accepts:
    1. Authorization: Bearer <RUNTIME_API_TOKEN> (constant-time verification)
    2. Valid founder session cookie (studio_session / agenthq_session)
    Raises 401 if unauthenticated and auth is enforced.
    """
    if not is_auth_enforced():
        return {"authenticated": True, "auth_type": "permissive_dev", "role": "founder"}

    # 1. Check Bearer token
    auth_header = request.headers.get("Authorization", "").strip()
    configured_runtime_token = get_runtime_api_token()

    if auth_header.startswith("Bearer "):
        provided_token = auth_header[len("Bearer "):].strip()
        if configured_runtime_token and provided_token:
            if secrets.compare_digest(provided_token, configured_runtime_token):
                return {
                    "authenticated": True,
                    "auth_type": "bearer_token",
                    "role": "runtime",
                }
        # If provided bearer token was invalid, reject immediately
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid runtime API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Check Session Cookie
    session = get_current_session(request)
    if session is not None:
        # Validate CSRF for cookie-based state-changing requests
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            verify_csrf(request, session)
        return {
            "authenticated": True,
            "auth_type": "session_cookie",
            "role": session.get("role", "founder"),
            "username": session.get("username", "founder"),
            "session": session,
        }

    # 3. Neither valid Bearer nor valid session present
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide a valid Bearer token or session.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_founder_auth(request: Request) -> dict[str, Any]:
    """Strictly requires founder authorization for privileged actions."""
    auth_result = require_runtime_auth(request)
    role = auth_result.get("role")
    if role not in ("founder", "runtime"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privileged operation requires founder authorization.",
        )
    return auth_result


def verify_csrf(request: Request, session: dict[str, Any]) -> None:
    """Validate Origin/Referer and CSRF token for cookie-based mutating requests."""
    # Check Origin / Referer against allowed origins
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        allowed = get_allowed_cors_origins()
        # Extract base origin (protocol + host[:port])
        matched = False
        for allowed_origin in allowed:
            if origin.startswith(allowed_origin):
                matched = True
                break
        if not matched and is_production():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Untrusted cross-origin request rejected.",
            )

    # Check X-CSRF-Token header if present
    csrf_header = request.headers.get("x-csrf-token", "").strip()
    expected_csrf = session.get("csrf_token", "")
    if csrf_header and expected_csrf:
        if not secrets.compare_digest(csrf_header, expected_csrf):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token validation failed.",
            )


# --- Security Headers Middleware ---

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers

        # Content-Security-Policy (Permissive for Three.js / WebGL / Next.js)
        headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss: http: https:; "
            "object-src 'none'; "
            "frame-ancestors 'none';"
        )
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if is_production():
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


# --- Log Redaction for Sensitive Tickets and Tokens ---

class SensitiveParamLogFilter(logging.Filter):
    """Redacts raw tickets, tokens, and authorization credentials from log records."""
    TICKET_PATTERN = re.compile(r"([?&]ticket=)[^& \t\n\r\"']+", re.IGNORECASE)
    TOKEN_PATTERN = re.compile(r"([?&]token=)[^& \t\n\r\"']+", re.IGNORECASE)
    BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.args, tuple):
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    arg = self.TICKET_PATTERN.sub(r"\1[REDACTED]", arg)
                    arg = self.TOKEN_PATTERN.sub(r"\1[REDACTED]", arg)
                    arg = self.BEARER_PATTERN.sub(r"\1[REDACTED]", arg)
                new_args.append(arg)
            record.args = tuple(new_args)
        if isinstance(record.msg, str):
            record.msg = self.TICKET_PATTERN.sub(r"\1[REDACTED]", record.msg)
            record.msg = self.TOKEN_PATTERN.sub(r"\1[REDACTED]", record.msg)
            record.msg = self.BEARER_PATTERN.sub(r"\1[REDACTED]", record.msg)
        return True


def redact_sensitive_string(val: str) -> str:
    """Helper to redact ticket, token, or session secrets from messages and error details."""
    if not val:
        return val
    val = re.sub(r"([?&]ticket=)[^& \t\n\r\"']+", r"\1[REDACTED]", val, flags=re.IGNORECASE)
    val = re.sub(r"([?&]token=)[^& \t\n\r\"']+", r"\1[REDACTED]", val, flags=re.IGNORECASE)
    val = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]{8,}", r"\1[REDACTED]", val, flags=re.IGNORECASE)
    return val


def setup_security_log_filters() -> None:
    """Attach the sensitive log filter to standard logging handlers."""
    filter_instance = SensitiveParamLogFilter()
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, SensitiveParamLogFilter) for f in lg.filters):
            lg.addFilter(filter_instance)

