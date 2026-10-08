import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from apps.api.api.db.session import create_all_tables
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

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(
    title="TrustFL Control Plane API",
    description="API for managing TrustFL federations, rounds, clients, and verification metadata.",
    version="0.1.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def require_production_api_key(request: Request, call_next):
    """Require the configured API key for non-public production endpoints."""
    is_public = request.url.path == "/health/" or request.method == "OPTIONS"
    if os.getenv("ENVIRONMENT", "development").lower() == "production" and not is_public:
        expected = os.getenv("API_SECRET_KEY", "")
        authorization = request.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not supplied or supplied != expected:
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

# Startup event for dev only
@app.on_event("startup")
def startup_event():
    from apps.api.api.db.session import check_config
    check_config(app)
    if os.getenv("ENVIRONMENT", "development").lower() != "production":
        create_all_tables()

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
