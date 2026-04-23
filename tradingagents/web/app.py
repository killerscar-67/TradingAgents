"""FastAPI application factory for the TradingAgents web UI (Phase 9)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tradingagents.web.routes.analysis import router as analysis_router
from tradingagents.web.routes.consultant import router as consultant_router
from tradingagents.web.routes.models import router as models_router

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="TradingAgents Web UI", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # Vite dev server
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(analysis_router)
    app.include_router(consultant_router)
    app.include_router(models_router)

    # Serve built frontend when dist/ exists (production local use)
    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")

    return app


app = create_app()
