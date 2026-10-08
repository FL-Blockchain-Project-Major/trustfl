from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging

from apps.api.api.routers import health, federations, clients, rounds, updates, artifacts, proofs, blockchain
from apps.api.api.db.session import create_all_tables
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(
    title="TrustFL Control Plane API",
    description="API for managing TrustFL federations, rounds, clients, and verification metadata.",
    version="0.1.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Secure defaults
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

# Startup event for dev only
@app.on_event("startup")
def startup_event():
    from apps.api.api.db.session import check_config
    check_config(app)
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
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": str(exc), "data": None}
    )
