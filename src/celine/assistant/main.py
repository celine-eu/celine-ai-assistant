from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import kb_collections, kb_sources
from .auth import AuthError
from .history import HistoryStore
from .kb_store import KbStore
from .llm import configuration_problems
from .logging_ import configure_logging
from .routes import router
from .settings import settings

configure_logging(settings.log_level)
log = logging.getLogger(__name__)


def json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = configuration_problems(settings)
    if problems:
        raise RuntimeError("model configuration: " + "; ".join(problems))
    for name in kb_sources.removed_ingestion_settings(settings):
        log.warning(
            "%s is no longer read: register knowledge sources per community with "
            "`celine-assistant kb source add`",
            name,
        )
    kb_collections.check_startup(kb_collections.qdrant_client())
    app.state.history_store = HistoryStore()

    if settings.kb_sync_on_start:
        results = await kb_sources.sync_all(kb_store=KbStore())
        log.info("kb_sources_synced", extra={"sources": len(results)})

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
