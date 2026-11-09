"""NullFace (Kavach-AI) — FastAPI async gateway.

    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router, ws_router
from .core.config import settings
from .core.db import get_db
from .services.scamradar_service import index


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()          # create schema
    index()           # warm the coercion index
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Real-Time Adversarial Image Immunization, Cryptographic Deepfake Invalidation & Multimodal Fraud Defense Protocol",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(ws_router)

if settings.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=settings.FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def spa_root():
        return FileResponse(settings.FRONTEND_DIR / "index.html")

    @app.get("/{asset}", include_in_schema=False)
    def spa_asset(asset: str):
        p = settings.FRONTEND_DIR / asset
        if p.is_file():
            return FileResponse(p)
        return FileResponse(settings.FRONTEND_DIR / "index.html")
