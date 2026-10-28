"""FastAPI application entrypoint.

Run with::

    uvicorn replay_api.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from replay_api.config import get_settings
from replay_api.db import create_tables
from replay_api.routes import router

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if get_settings().create_tables_on_startup:
        create_tables()
    yield


app = FastAPI(
    title="API Traffic Replay",
    version="0.1.0",
    description="Stores request collections, baselines, and regression reports.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if WEB_DIST.is_dir():
    assets = WEB_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/{spa_path:path}")
    def spa_fallback(spa_path: str) -> FileResponse:
        # Keep API and docs paths authoritative even when a catch-all exists.
        if spa_path == "health" or spa_path.startswith(
            ("v1/", "docs", "redoc", "openapi", "assets/")
        ):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = WEB_DIST / spa_path
        if spa_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
