"""Environment-configured demo analyst authentication for RingTrace.

The main application deliberately remains readable without login. Only the
simulated-action routes depend on an authenticated, server-issued session.
Sessions are signed with itsdangerous, stored in an HttpOnly cookie, and
revocable in this single-process hackathon demo.
"""
from __future__ import annotations

import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from fastapi import Header, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "ringtrace_analyst_session"
SESSION_COOKIE_PATH = "/api"
SESSION_COOKIE_SAMESITE = "lax"
SESSION_SALT = "ringtrace-analyst-session-v1"
DEFAULT_SESSION_TTL_SECONDS = 8 * 60 * 60
DEFAULT_APPROVAL_TTL_SECONDS = 5 * 60
MIN_SECRET_BYTES = 32


@dataclass(frozen=True)
class DemoAuthConfig:
    secret: str = field(repr=False)
    username: str
    password: str = field(repr=False)
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    approval_ttl_seconds: int = DEFAULT_APPROVAL_TTL_SECONDS


@dataclass(frozen=True)
class AnalystSession:
    username: str
    session_id: str
    csrf_token: str
    issued_at: int
    expires_at: int

    @property
    def expires_at_iso(self) -> str:
        return datetime.fromtimestamp(self.expires_at, tz=timezone.utc).isoformat()


class AuthSessionRegistry:
    """Small revocation list matching the API's process-local case store."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._expires: dict[str, int] = {}

    def add(self, session_id: str, expires_at: int) -> None:
        now = int(time.time())
        with self._lock:
            expired = [key for key, expiry in self._expires.items() if expiry <= now]
            for key in expired:
                self._expires.pop(key, None)
            self._expires[session_id] = expires_at

    def is_active(self, session_id: str) -> bool:
        now = int(time.time())
        with self._lock:
            expires_at = self._expires.get(session_id)
            if expires_at is None:
                return False
            if expires_at <= now:
                self._expires.pop(session_id, None)
                return False
            return True

    def revoke(self, session_id: str) -> None:
        with self._lock:
            self._expires.pop(session_id, None)


@dataclass(frozen=True)
class AuthenticatedAnalyst:
    username: str
    session_id: str
    csrf_token: str
    expires_at: int


def get_demo_auth_config() -> DemoAuthConfig | None:
    """Read credentials on demand; incomplete or weak configuration disables auth."""
    secret = os.getenv("RINGTRACE_AUTH_SECRET", "").strip()
    username = os.getenv("RINGTRACE_DEMO_USERNAME", "")
    password = os.getenv("RINGTRACE_DEMO_PASSWORD", "")
    if not secret or not username.strip() or not password:
        return None
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        return None
    try:
        session_ttl = int(os.getenv("RINGTRACE_SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)))
        approval_ttl = int(os.getenv("RINGTRACE_APPROVAL_TTL_SECONDS", str(DEFAULT_APPROVAL_TTL_SECONDS)))
    except ValueError:
        return None
    if not 1 <= session_ttl <= 24 * 60 * 60 or not 1 <= approval_ttl <= 60 * 60:
        return None
    return DemoAuthConfig(
        secret=secret,
        username=username,
        password=password,
        session_ttl_seconds=session_ttl,
        approval_ttl_seconds=approval_ttl,
    )


def credentials_match(username: str, password: str, config: DemoAuthConfig) -> bool:
    """Compare both configured values in constant time without short-circuiting."""
    user_match = hmac.compare_digest(username.encode("utf-8"), config.username.encode("utf-8"))
    password_match = hmac.compare_digest(password.encode("utf-8"), config.password.encode("utf-8"))
    return user_match and password_match


def _serializer(config: DemoAuthConfig) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.secret, salt=SESSION_SALT)


def issue_session(username: str, config: DemoAuthConfig, registry: AuthSessionRegistry) -> tuple[str, AnalystSession]:
    now = int(time.time())
    session = AnalystSession(
        username=username,
        session_id=secrets.token_urlsafe(24),
        csrf_token=secrets.token_urlsafe(32),
        issued_at=now,
        expires_at=now + config.session_ttl_seconds,
    )
    token = _serializer(config).dumps({
        "sub": session.username,
        "sid": session.session_id,
        "csrf": session.csrf_token,
        "iat": session.issued_at,
    })
    registry.add(session.session_id, session.expires_at)
    return token, session


def read_session(token: str | None, config: DemoAuthConfig, registry: AuthSessionRegistry) -> AnalystSession | None:
    if not token:
        return None
    try:
        payload: Any = _serializer(config).loads(token, max_age=config.session_ttl_seconds)
    except (BadSignature, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    username, session_id, csrf_token, issued_at = (
        payload.get("sub"), payload.get("sid"), payload.get("csrf"), payload.get("iat")
    )
    if (not isinstance(username, str) or not username
            or not isinstance(session_id, str) or not session_id
            or not isinstance(csrf_token, str) or not csrf_token
            or not isinstance(issued_at, int) or isinstance(issued_at, bool)):
        return None
    if username != config.username or not registry.is_active(session_id):
        return None
    return AnalystSession(
        username=username,
        session_id=session_id,
        csrf_token=csrf_token,
        issued_at=issued_at,
        expires_at=issued_at + config.session_ttl_seconds,
    )


def cookie_is_secure(request: Request) -> bool:
    """Default to Secure; allow an explicit opt-out only for local HTTP demos."""
    explicit = os.getenv("RINGTRACE_AUTH_COOKIE_SECURE", "").strip().lower()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    request_is_https = request.url.scheme.lower() == "https" or forwarded_proto == "https"
    if explicit in {"1", "true", "yes", "on"}:
        return True
    if explicit in {"0", "false", "no", "off"}:
        # The opt-out is only for plain-HTTP localhost development. A non-local
        # HTTP host remains Secure even if the environment is misconfigured.
        hostname = (request.url.hostname or "").lower().strip("[]")
        local_http = hostname in {"localhost", "127.0.0.1", "::1"}
        return request_is_https or not local_http
    # Unknown values and an unset value fail secure rather than silently
    # weakening the cookie behind an unconfigured reverse proxy.
    return True


def set_session_cookie(response, request: Request, token: str, config: DemoAuthConfig) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=config.session_ttl_seconds,
        path=SESSION_COOKIE_PATH,
        secure=cookie_is_secure(request),
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response, request: Request) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path=SESSION_COOKIE_PATH,
        secure=cookie_is_secure(request),
        httponly=True,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def reject_cross_site_fetch(request: Request) -> None:
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site authentication requests are not allowed.")


def require_authenticated_analyst(request: Request) -> AuthenticatedAnalyst:
    config = get_demo_auth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="Demo analyst authentication is not configured.")
    registry: AuthSessionRegistry = request.app.state.auth_sessions
    session = read_session(request.cookies.get(SESSION_COOKIE_NAME), config, registry)
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in as the configured demo analyst to continue.")
    return AuthenticatedAnalyst(
        username=session.username,
        session_id=session.session_id,
        csrf_token=session.csrf_token,
        expires_at=session.expires_at,
    )


def require_action_analyst(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthenticatedAnalyst:
    analyst = require_authenticated_analyst(request)
    reject_cross_site_fetch(request)
    if not x_csrf_token or not hmac.compare_digest(analyst.csrf_token, x_csrf_token):
        raise HTTPException(status_code=403, detail="A valid same-origin CSRF token is required.")
    return analyst
