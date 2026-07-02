from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from ipaddress import ip_address
from time import monotonic
from typing import Deque

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, csp: str, hsts_enabled: bool) -> None:
        super().__init__(app)
        self._csp = csp.strip()
        self._hsts_enabled = hsts_enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if self._csp:
            response.headers.setdefault("Content-Security-Policy", self._csp)
        if self._hsts_enabled:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, max_body_bytes: int) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_bytes = int(content_length)
            except ValueError:
                return JSONResponse({"detail": "invalid content-length"}, status_code=400)
            if body_bytes > self._max_body_bytes:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
        return await call_next(request)


@dataclass(frozen=True)
class _RatePolicy:
    name: str
    limit: int


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        window_seconds: int,
        login_limit: int,
        api_limit: int,
    ) -> None:
        super().__init__(app)
        self._window_seconds = window_seconds
        self._login_policy = _RatePolicy("login", login_limit)
        self._api_policy = _RatePolicy("api", api_limit)
        self._events: dict[str, Deque[float]] = {}
        self._last_cleanup = 0.0

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        policy = self._policy_for(request)
        if policy is None:
            return await call_next(request)

        now = monotonic()
        self._cleanup(now)
        key = f"{policy.name}:{_client_ip(request)}"
        events = self._events.setdefault(key, deque())
        self._prune(events, now)

        if len(events) >= policy.limit:
            retry_after = max(1, int(self._window_seconds - (now - events[0]))) if events else self._window_seconds
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        events.append(now)
        response = await call_next(request)
        response.headers.setdefault("X-RateLimit-Limit", str(policy.limit))
        response.headers.setdefault("X-RateLimit-Remaining", str(max(0, policy.limit - len(events))))
        return response

    def _policy_for(self, request: Request) -> _RatePolicy | None:
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/auth/login":
            return self._login_policy
        if path.startswith("/api/"):
            return self._api_policy
        return None

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self._window_seconds:
            return
        empty_keys: list[str] = []
        for key, events in self._events.items():
            self._prune(events, now)
            if not events:
                empty_keys.append(key)
        for key in empty_keys:
            self._events.pop(key, None)
        self._last_cleanup = now

    def _prune(self, events: Deque[float], now: float) -> None:
        cutoff = now - self._window_seconds
        while events and events[0] <= cutoff:
            events.popleft()


def install_security_middleware(app: FastAPI, settings: Settings) -> None:
    allowed_hosts = settings.allowed_hosts
    if allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=settings.security_max_body_bytes)
    if settings.security_rate_limit_enabled:
        app.add_middleware(
            InMemoryRateLimitMiddleware,
            window_seconds=settings.security_rate_limit_window_seconds,
            login_limit=settings.security_login_rate_limit_per_minute,
            api_limit=settings.security_api_rate_limit_per_minute,
        )
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp=settings.security_csp,
        hsts_enabled=settings.security_enable_hsts,
    )


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    if _is_trusted_proxy_peer(peer):
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip() or peer or "unknown"
    return peer or "unknown"


def _is_trusted_proxy_peer(host: str) -> bool:
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback
