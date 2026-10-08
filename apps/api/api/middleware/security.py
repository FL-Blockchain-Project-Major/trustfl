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
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("trustfl.audit")

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


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests whose bodies exceed MAX_BODY_BYTES."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method in MUTATING_METHODS:
            content_length = request.headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large. Maximum allowed: 1 MB."},
                )
            if not content_length:
                body = await request.body()
                if len(body) > MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large. Maximum allowed: 1 MB."},
                    )
        return await call_next(request)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Structured audit log for every API request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        client_ip = request.client.host if request.client else "unknown"

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
