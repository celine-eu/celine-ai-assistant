from __future__ import annotations

import logging
import sys


class DefaultContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        if not hasattr(record, "user_id"):
            record.user_id = "-"
        return True


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(DefaultContextFilter())

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s request_id=%(request_id)s user_id=%(user_id)s"
    )
    handler.setFormatter(formatter)

    root.addHandler(handler)

    # optional: tune noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("qdrant_client").setLevel(logging.INFO)
    logging.getLogger("openai").setLevel(logging.INFO)

    # Keep uvicorn access disabled if you want
    logging.getLogger("uvicorn.access").handlers.clear()
