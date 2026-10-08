import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from apps.api.api.db.session import create_all_tables
from apps.api.api.middleware.security import AuditLogMiddleware, RequestSizeLimitMiddleware
from apps.api.api.routers import (
    artifacts,
    blockchain,
    clients,
    federations,
    health,
    proofs,
    rounds,
    updates,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

def rate_limit_key(request: Request) -> str:
    """Honor X-Forwarded-For only when the immediate proxy is trusted."""
    trusted = {x.strip() for x in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if x.strip()}
    peer = request.client.host if request.client else "unknown"
    if peer in trusted:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key, default_limits=[os.getenv("API_RATE_LIMIT", "100/minute")])


@asynccontextmanager
async def lifespan(app: FastAPI):
    from apps.api.api.db.session import check_config
    check_config(app)
    if os.getenv("ENVIRONMENT", "development").lower() == "development":
        create_all_tables()
    yield

app = FastAPI(
    title="TrustFL Control Plane API",
    description="API for managing TrustFL federations, rounds, clients, and verification metadata.",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next):
    """Apply SlowAPI's global limit, including routes without decorators."""
    if request.method != "OPTIONS":
        try:
            limiter._check_request_limit(request, None, in_middleware=True)
        except RateLimitExceeded as exc:
            return _rate_limit_exceeded_handler(request, exc)
    return await call_next(request)


@app.middleware("http")
async def require_production_api_key(request: Request, call_next):
    """Require a role-scoped API key for non-public production endpoints."""
    is_public = request.url.path == "/health/" or request.method == "OPTIONS"
    configured = os.getenv("API_AUTH_REQUIRED")
    auth_required = (
        configured.lower() == "true"
        if configured is not None
        else os.getenv("ENVIRONMENT", "development").lower() != "development"
    )
    if auth_required and not is_public:
        authorization = request.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ").strip()
        role = "admin" if request.method == "DELETE" else (
            "read" if request.method in {"GET", "HEAD"} else "write"
        )
        keys = {
            "read": os.getenv("API_READ_KEY", ""),
            "write": os.getenv("API_WRITE_KEY", ""),
            "admin": os.getenv("API_ADMIN_KEY", ""),
        }
        valid = any(
            expected
            and hmac.compare_digest(supplied, expected)
            and (key_role == role or key_role == "admin")
            for key_role, expected in keys.items()
        )
        if not valid and (
            os.getenv("API_LEGACY_AUTH_COMPAT", "false").lower() == "true"
            or not any(keys.values())
        ):
            legacy = os.getenv("API_SECRET_KEY", "")
            valid = bool(legacy and hmac.compare_digest(supplied, legacy))
        if not valid:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Authentication required.", "data": None},
            )
    return await call_next(request)

def configured_cors_origins() -> list[str]:
    """Return the explicitly configured browser origins."""
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        if not origins:
            raise RuntimeError("CORS_ALLOWED_ORIGINS must be configured in production")
        if "*" in origins:
            raise RuntimeError("Wildcard CORS origins are not allowed in production")
        return origins
    return origins or ["http://localhost:3000", "http://127.0.0.1:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(AuditLogMiddleware)

# Include routers
app.include_router(health.router)
app.include_router(federations.router)
app.include_router(clients.router)
app.include_router(rounds.router)
app.include_router(updates.router)
app.include_router(artifacts.router)
app.include_router(proofs.router)
app.include_router(blockchain.router)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, _exc: Exception):
    logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "An internal server error occurred.", "data": None}
    )
