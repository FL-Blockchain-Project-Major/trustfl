"""
Security middleware for TrustFL API.

Provides:
  - Request body size limits (anti-oversized-payload)
  - Structured audit log on every mutating request
  - Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("trustfl.audit")

def _client_ip(request: Request) -> str:
    trusted = {item.strip() for item in os.environ.get("TRUSTED_PROXY_IPS", "").split(",") if item.strip()}
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded if peer in trusted and forwarded else peer

# 1 MB limit on request bodies
MAX_BODY_BYTES = 1 * 1024 * 1024

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cache-Control": "no-store",
}


class RequestSizeLimitMiddleware:
    """Bound mutating request streams without requiring Content-Length.

    The receive wrapper counts chunks as downstream consumes them; it never
    joins or pre-buffers an untrusted body.  A bodiless DELETE is therefore
    treated as a zero-byte request while chunked uploads are capped too.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] not in MUTATING_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length", b"")
        if raw_length.isdigit() and int(raw_length) > MAX_BODY_BYTES:
            response = JSONResponse(status_code=413, content={"detail": "Request body too large. Maximum allowed: 1 MB."})
            await response(scope, receive, send)
            return
        size = 0
        exceeded = False

        async def limited_receive():
            nonlocal size, exceeded
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > MAX_BODY_BYTES:
                    exceeded = True
                    # Starlette turns a disconnect during body consumption
                    # into a controlled request failure.  We replace it with
                    # a 413 below and suppress any partial application reply.
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message):
            if not exceeded:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            response = JSONResponse(status_code=413, content={"detail": "Request body too large. Maximum allowed: 1 MB."})
            await response(scope, receive, send)


class GlobalRateLimitMiddleware:
    """Small, explicit in-process fixed-window limiter for every request.

    SlowAPI only applies limits to decorated endpoints; this API uses routers
    without decorators, so its middleware silently did not enforce defaults.
    This middleware deliberately sits outside authentication, thus failed key
    guesses consume the same per-IP budget. Deployments with multiple API
    workers must use a shared gateway/Redis limiter in addition to this guard.
    """

    def __init__(self, app, limit: str | None = None) -> None:
        self.app = app
        self.limit = limit
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    @staticmethod
    def _parse(value: str) -> tuple[int, float]:
        count, period = value.strip().lower().split("/", 1)
        seconds = {"second": 1, "minute": 60, "hour": 3600}.get(period.rstrip("s"))
        if not seconds or int(count) <= 0:
            raise ValueError("API_RATE_LIMIT must be e.g. 100/minute")
        return int(count), float(seconds)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["method"] != "OPTIONS":
            limit, period = self._parse(self.limit or os.getenv("API_RATE_LIMIT", "100/minute"))
            now = time.monotonic()
            peer = (scope.get("client") or ("unknown", 0))[0]
            headers = dict(scope.get("headers", []))
            trusted = {item.strip() for item in os.environ.get("TRUSTED_PROXY_IPS", "").split(",") if item.strip()}
            forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()
            key = forwarded if peer in trusted and forwarded else peer
            with self._lock:
                started, count = self._windows.get(key, (now, 0))
                if now - started >= period:
                    started, count = now, 0
                count += 1
                self._windows[key] = (started, count)
            if count > limit:
                response = JSONResponse(status_code=429, content={"detail": "Rate limit exceeded."})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Structured audit log for every API request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        client_ip = _client_ip(request)

        log_entry = {
            "event": "api_request",
            "request_id": request_id,
            "method": request.method,
            "path": str(request.url.path),
            "status_code": response.status_code,
            "client_ip": client_ip,
            "duration_ms": duration_ms,
        }

        if response.status_code >= 400:
            logger.warning(json.dumps(log_entry))
        else:
            logger.info(json.dumps(log_entry))

        # Attach security headers to every response
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        response.headers["X-Request-ID"] = request_id

        return response
