from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .history import HistoryStore

from .qdrant_setup import ensure_collection
from .settings import settings
from .logging_ import configure_logging
from .routes import router
from .auth import AuthError

configure_logging(settings.log_level)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):

    ensure_collection()

    app.state.history_store = HistoryStore(settings.chat_db_path)

    log.info("app started")

    try:
        yield
    finally:
        log.info("app stopped")


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


def json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


@app.on_event("startup")
async def startup():
    ingest_service = IngestService()
    app.state.ingest_service = ingest_service
    await ingest_service.start()


@app.on_event("shutdown")
async def shutdown():
    svc: IngestService = app.state.ingest_service
    await svc.stop()


app.include_router(router)
