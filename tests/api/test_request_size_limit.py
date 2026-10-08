import httpx
import pytest
from fastapi import FastAPI, Request

from apps.api.api.middleware.security import MAX_BODY_BYTES, RequestSizeLimitMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware)

    @app.post("/payload")
    async def payload(request: Request):
        return {"size": len(await request.body())}

    @app.delete("/payload")
    async def delete_payload():
        return {"deleted": True}

    return app


@pytest.mark.asyncio
async def test_bodiless_delete_is_valid():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://test") as client:
        assert (await client.delete("/payload")).status_code == 200


@pytest.mark.asyncio
async def test_chunked_normal_and_oversized_requests():
    async def normal():
        yield b"a" * 10
        yield b"b" * 11

    async def oversized():
        yield b"a" * MAX_BODY_BYTES
        yield b"b"

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://test") as client:
        assert (await client.post("/payload", content=normal())).json() == {"size": 21}
        assert (await client.post("/payload", content=oversized())).status_code == 413


@pytest.mark.asyncio
async def test_declared_oversized_request_is_rejected_before_reading():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.post("/payload", content=b"x", headers={"Content-Length": str(MAX_BODY_BYTES + 1)})
    assert response.status_code == 413
