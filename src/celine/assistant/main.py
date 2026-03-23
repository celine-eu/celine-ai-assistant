from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .auth import AuthError
from .history import HistoryStore
from .logging_ import configure_logging
from .qdrant_setup import ensure_collection
from .routes import router
from .settings import settings
from .training_materials import startup_sync_training_materials

configure_logging(settings.log_level)
log = logging.getLogger(__name__)


def json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_collection()
    app.state.history_store = HistoryStore()

    if settings.ingest_enable:
        try:
            result = await startup_sync_training_materials()
            log.info("training_materials_synced", extra=result)
        except Exception:
            log.exception(
                "training_materials_sync_failed",
                extra={"root": settings.training_materials_path},
            )

    log.info("app started")
    try:
        yield
    finally:
        log.info("app stopped")


def create_app():
    app = FastAPI(
        title="CELINE Chatbot API",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env != "prod" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def error_boundary(request: Request, call_next):
        try:
            return await call_next(request)
        except AuthError as e:
            return json_error(401, str(e))
        except Exception:
            log.exception("unhandled_error")
            return json_error(500, "Internal Server Error")

    app.include_router(router)

    return app
