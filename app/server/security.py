"""
Security helpers — opt-in API token auth, CORS origins, and call rate limiting.

Everything here is OPT-IN. With no security env vars set, the application
behaves exactly as before (a warning is logged at startup). This keeps the
existing demo/dev flow working while making it easy to lock down for any
real deployment.
"""

import logging
import secrets
import time
from collections import deque

from fastapi import Header, HTTPException, Query, Request, status

from app.config.settings import settings

logger = logging.getLogger(__name__)


# ─── Token authentication ──────────────────────────────────────────────────

def auth_enabled() -> bool:
    """True when an API auth token is configured."""
    return bool(settings.api_auth_token)


def _extract_token(
    request: Request,
    x_api_key: str | None,
    authorization: str | None,
    token_qs: str | None,
) -> str | None:
    """Pull a token from header, bearer auth, or query param (in that order)."""
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if token_qs:
        return token_qs
    return None


def is_valid_token(candidate: str | None) -> bool:
    """Constant-time compare against the configured token."""
    if not candidate:
        return False
    return secrets.compare_digest(candidate, settings.api_auth_token)


async def require_auth(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    """
    FastAPI dependency enforcing the API token when auth is enabled.

    No-op when auth is disabled (no token configured), preserving the
    current open behavior for dev/demo.
    """
    if not auth_enabled():
        return
    candidate = _extract_token(request, x_api_key, authorization, token)
    if not is_valid_token(candidate):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── CORS origins ───────────────────────────────────────────────────────────

def get_cors_origins() -> list[str]:
    """
    Resolve the allowed CORS origins.

    If ALLOWED_ORIGINS is unset, default to localhost on the configured port
    (the dashboard is same-origin, so this only affects cross-origin callers).
    """
    raw = (settings.allowed_origins or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    port = settings.port
    return [
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    ]


# ─── Simple in-memory rate limiter ──────────────────────────────────────────

class SlidingWindowRateLimiter:
    """
    Per-process sliding-window limiter keyed by client identity.

    NOTE: in-memory and per-process — correct only for a single uvicorn
    worker. Multi-worker deployments would need shared state (e.g. Redis).
    """

    def __init__(self, max_per_minute: int):
        self._max = max_per_minute
        self._window = 60.0
        self._hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        if self._max <= 0:
            return True  # unlimited
        now = time.monotonic()
        dq = self._hits.setdefault(key, deque())
        cutoff = now - self._window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self._max:
            return False
        dq.append(now)
        return True


# Singleton limiter for outbound-call triggers.
_call_limiter = SlidingWindowRateLimiter(settings.call_rate_limit_per_minute)


async def call_rate_limit(request: Request) -> None:
    """FastAPI dependency: throttle outbound-call trigger endpoints."""
    client = request.client.host if request.client else "unknown"
    if not _call_limiter.allow(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Call rate limit exceeded. Try again shortly.",
        )
