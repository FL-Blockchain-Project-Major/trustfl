"""Clean-interpreter ASGI tests avoid this environment's pytest/HTTPX deadlock."""

from __future__ import annotations

import subprocess
import sys


def _run(script: str) -> str:
    return subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_global_limiter_cannot_silently_become_inactive_or_skip_bad_keys():
    assert (
        _run("""
import asyncio, httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from apps.api.api.middleware.security import GlobalRateLimitMiddleware
async def main():
 app=FastAPI(); app.add_middleware(GlobalRateLimitMiddleware, limit="5/minute")
 @app.get("/health/")
 async def health(): return {"ok": True}
 @app.get("/bad")
 async def bad(): return JSONResponse(status_code=401, content={})
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
  print([(await c.get("/health/")).status_code for _ in range(12)])
asyncio.run(main())
""")
        == "[200, 200, 200, 200, 200, 429, 429, 429, 429, 429, 429, 429]"
    )


def test_options_is_exempt_from_global_limiter():
    assert (
        _run("""
import asyncio, httpx
from fastapi import FastAPI
from apps.api.api.middleware.security import GlobalRateLimitMiddleware
async def main():
 app=FastAPI(); app.add_middleware(GlobalRateLimitMiddleware, limit="1/minute")
 @app.get("/x")
 async def x(): return {"ok": True}
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
  print([(await c.options("/x")).status_code for _ in range(3)], (await c.get("/x")).status_code)
asyncio.run(main())
""")
        == "[405, 405, 405] 200"
    )


def test_failed_authentication_attempts_are_limited():
    assert (
        _run("""
import asyncio, httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from apps.api.api.middleware.security import GlobalRateLimitMiddleware
async def main():
 app=FastAPI(); app.add_middleware(GlobalRateLimitMiddleware, limit="5/minute")
 @app.get("/bad")
 async def bad(): return JSONResponse(status_code=401, content={})
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
  print([(await c.get("/bad", headers={"X-API-Key":"guess"})).status_code for _ in range(30)])
asyncio.run(main())
""")
        == "[401, 401, 401, 401, 401, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429, 429]"
    )
