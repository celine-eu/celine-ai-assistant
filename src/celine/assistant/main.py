from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from celine.sdk.posture import docs_urls
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import kb_collections, kb_sources
from .auth import AuthError
from .history import HistoryStore
from .kb_store import KbStore
from .llm import configuration_problems
from .logging_ import configure_logging
from .posture import current_env, enforce_posture, is_dev
from .routes import router
from .settings import settings

configure_logging(settings.log_level)
log = logging.getLogger(__name__)


def json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


@asynccontextmanager
async def lifespan(app: FastAPI):
    # First, before Qdrant or the database is reached: outside CELINE_ENV=dev every
    # development-only value is refused here, all of them in one message.
    enforce_posture()
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


# Set on every response unless the route set its own (`/attachments/{id}/raw` does).
# JSON and event streams need no content policy beyond "nothing"; the interactive API
# docs (HTML) load their own scripts and are left without one.
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
)
_API_CSP = b"default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    """Adds `_SECURITY_HEADERS`, and `_API_CSP` to any non-HTML response."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for name, value in _SECURITY_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                content_type = next(
                    (v for k, v in headers if k.lower() == b"content-type"), b""
                )
                if (
                    b"content-security-policy" not in present
                    and not content_type.startswith(b"text/html")
                ):
                    headers.append((b"content-security-policy", _API_CSP))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send)


def create_app():
    app = FastAPI(
        title="CELINE Chatbot API",
        version="0.2.0",
        lifespan=lifespan,
        # Same signal as the CORS below: outside dev /docs, /redoc and /openapi.json
        # are not mounted unless CELINE_PUBLIC_DOCS=true.
        **docs_urls(env=current_env()),
    )

    # Wildcard origins (with credentials) only in dev. This used to be every
    # APP_ENV other than exactly "prod" — so "production" or "staging" got it.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if is_dev() else [],
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

    # Last added is outermost: error responses get the headers too.
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(router)

    return app
