"""Disposable API with two versions and one slow route.

``/v1`` is the baseline. ``/v2`` plants three differences:

- ``GET /health`` returns 500 instead of 200
- ``GET /order`` renames ``sku`` to ``product_sku``
- ``GET /clock`` changes only ``created_at``, which the sample request file ignores

``GET /delay`` waits without blocking a worker so the concurrency benchmark
can overlap real requests. The engine does not import this app.
"""

import asyncio

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse


def create_app() -> FastAPI:
    app = FastAPI(title="Replay demo API", redirect_slashes=False)
    app.include_router(_version_router("v1"), prefix="/v1")
    app.include_router(_version_router("v2"), prefix="/v2")

    @app.get("/delay")
    async def delay(ms: int = 20) -> dict[str, bool]:
        bounded = min(max(ms, 0), 1000)
        await asyncio.sleep(bounded / 1000)
        return {"ok": True}

    return app


def _version_router(version: str) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> JSONResponse:
        if version == "v2":
            response = JSONResponse({"status": "down"}, status_code=500)
        else:
            response = JSONResponse({"status": "ok"}, status_code=200)
        response.headers["set-cookie"] = f"session={version}-secret"
        return response

    @router.get("/order")
    def order() -> dict[str, str]:
        if version == "v2":
            return {
                "id": "ord_1",
                "product_sku": "A",
                "created_at": "2024-06-01T00:00:00+00:00",
            }
        return {
            "id": "ord_1",
            "sku": "A",
            "created_at": "2020-01-01T00:00:00+00:00",
        }

    @router.get("/clock")
    def clock() -> dict[str, str]:
        created_at = "2024-06-01T00:00:00+00:00" if version == "v2" else "2020-01-01T00:00:00+00:00"
        return {"status": "ok", "created_at": created_at}

    return router


app = create_app()
