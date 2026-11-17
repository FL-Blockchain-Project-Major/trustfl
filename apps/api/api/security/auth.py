"""Request authentication, least-privilege authorization, and tenant scoping."""

from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class AuthContext:
    role: str
    federations: frozenset[str]
    identity: str | None = None

    def can_access_federation(self, federation_id: str) -> bool:
        return "*" in self.federations or federation_id in self.federations


def _configured() -> bool:
    value = os.getenv("API_AUTH_REQUIRED")
    return (
        value.lower() == "true"
        if value is not None
        else os.getenv("ENVIRONMENT", "development").lower() != "development"
    )


def authenticate(request: Request) -> AuthContext:
    current = getattr(request.state, "auth", None)
    if current is not None:
        return current
    if not _configured():
        return AuthContext("admin", frozenset({"*"}))
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    keys = {
        "read": os.getenv("API_READ_KEY", ""),
        "write": os.getenv("API_WRITE_KEY", ""),
        "admin": os.getenv("API_ADMIN_KEY", ""),
    }
    role = next(
        (
            candidate
            for candidate, expected in keys.items()
            if expected and hmac.compare_digest(supplied, expected)
        ),
        None,
    )
    if role is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    configured = os.getenv(f"API_{role.upper()}_FEDERATIONS", "*")
    federations = frozenset(item.strip() for item in configured.split(",") if item.strip())
    return AuthContext(role, federations or frozenset({"*"}))


def require_permission(permission: str):
    def dependency(request: Request) -> AuthContext:
        context = authenticate(request)
        if context.role != "admin" and context.role != permission:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permission")
        match = re.search(r"/federation/([^/]+)", request.url.path)
        if match and not context.can_access_federation(match.group(1)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
        return context

    return dependency


def require_admin(request: Request) -> AuthContext:
    context = authenticate(request)
    if context.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator authorization required")
    return context


def require_federation_access(context: AuthContext, federation_id: str) -> None:
    if not context.can_access_federation(federation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
