"""
Security middleware for TrustFL API.

Provides:
  - Request body size limits (anti-oversized-payload)
  - Structured audit log on every mutating request
  - Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
"""

from __future__ import annotations

import hashlib
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
from trustfl_observability import metrics
from trustfl_observability.tracing import trace_context

logger = logging.getLogger("trustfl.audit")


def _client_ip(request: Request) -> str:
    trusted = {
        item.strip() for item in os.environ.get("TRUSTED_PROXY_IPS", "").split(",") if item.strip()
    }
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded if peer in trusted and forwarded else peer


# 1 MB limit on request bodies
MAX_BODY_BYTES = 1 * 1024 * 1024
MAX_PROOF_BODY_BYTES = 256 * 1024

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
        max_body = (
            MAX_PROOF_BODY_BYTES if b"/proof" in scope.get("path", "").encode() else MAX_BODY_BYTES
        )
        if raw_length.isdigit() and int(raw_length) > max_body:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request body too large."},
            )
            await response(scope, receive, send)
            return
        size = 0
        exceeded = False

        async def limited_receive():
            nonlocal size, exceeded
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > max_body:
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
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request body too large."},
            )
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
        self._redis = None
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            try:
                import redis

                self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
            except Exception as exc:
                if os.getenv("ENVIRONMENT", "development").lower() == "production":
                    raise RuntimeError("REDIS_URL is configured but Redis is unavailable") from exc
                logger.warning(
                    "Redis rate limiter unavailable; using development-only local limiter"
                )

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
            trusted = {
                item.strip()
                for item in os.environ.get("TRUSTED_PROXY_IPS", "").split(",")
                if item.strip()
            }
            forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1").split(",")[0].strip()
            key = forwarded if peer in trusted and forwarded else peer
            path = scope.get("path", "")
            configured_limit = (
                os.getenv("API_ZKP_RATE_LIMIT", "10/minute")
                if "/proof" in path
                else os.getenv("API_UPDATE_RATE_LIMIT", "30/minute")
                if "/update" in path
                else self.limit or os.getenv("API_RATE_LIMIT", "100/minute")
            )
            limit, period = self._parse(configured_limit)
            identity = hashlib.sha256(headers.get(b"authorization", b"").strip()).hexdigest()[:16]
            keys = {f"{key}:{path}", f"identity:{identity}:{path}"}
            counts = []
            if self._redis is not None:
                for rate_key in keys:
                    bucket = f"trustfl:ratelimit:{rate_key}:{path}:{int(time.time() // period)}"
                    current = int(self._redis.incr(bucket))
                    if current == 1:
                        self._redis.expire(bucket, int(period) + 1)
                    counts.append(current)
            else:
                with self._lock:
                    for rate_key in keys:
                        started, count = self._windows.get(rate_key, (now, 0))
                        if now - started >= period:
                            started, count = now, 0
                        count += 1
                        self._windows[rate_key] = (started, count)
                        counts.append(count)
            if any(count > limit for count in counts):
                retry_after = max(1, int(period - (time.time() % period)))
                logger.warning(
                    "security_event=rate_limit_violation method=%s path=%s client_ip=%s",
                    scope.get("method"),
                    path,
                    key,
                )
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded."},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Structured audit log for every API request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        trace = trace_context(request.headers.get("traceparent"))
        request.state.trace_id = trace.trace_id
        request.state.span_id = trace.span_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            metrics.inc(
                "trustfl_api_requests_total",
                {
                    "method": request.method,
                    "route": _route_label(request.url.path),
                    "status": "500",
                },
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        client_ip = _client_ip(request)
        route = _route_label(request.url.path)
        metrics.inc(
            "trustfl_api_requests_total",
            {"method": request.method, "route": route, "status": str(response.status_code)},
        )
        metrics.observe(
            "trustfl_api_request_duration_seconds",
            duration_ms / 1000,
            {"method": request.method, "route": route},
        )
        if response.status_code >= 400:
            metrics.inc(
                "trustfl_api_errors_total", {"route": route, "status": str(response.status_code)}
            )

        log_entry = {
            "event": "api_request",
            "request_id": request_id,
            "method": request.method,
            "path": str(request.url.path),
            "status_code": response.status_code,
            "client_ip": client_ip,
            "duration_ms": duration_ms,
            "trace_id": trace.trace_id,
        }

        if response.status_code >= 400:
            logger.warning(json.dumps(log_entry))
        else:
            logger.info(json.dumps(log_entry))

        # Attach security headers to every response
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        response.headers["X-Request-ID"] = request_id
        response.headers["Traceparent"] = trace.traceparent

        return response


def _route_label(path: str) -> str:
    """Keep metric labels bounded by replacing resource identifiers."""
    parts = path.strip("/").split("/")
    normalized = []
    for part in parts:
        if not part:
            continue
        if len(part) >= 16 or part.startswith(
            ("fed_", "client_", "round_", "update_", "proof_", "artifact_", "tx_")
        ):
            normalized.append("{id}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized) if normalized else "/"
