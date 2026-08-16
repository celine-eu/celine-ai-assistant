"""Structured logging, and the one way it bites.

`logging` merges `extra` straight into the `LogRecord`'s `__dict__` and refuses to
overwrite an attribute it owns — by raising, from inside whatever `except` block the
call was written in. A log line is the last thing anyone expects to be the failing
statement, so the collision is worth a test of its own.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

# The attributes `logging.LogRecord.__init__` sets, which `makeRecord` then refuses to
# let `extra` replace.
RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info", "taskName",
    "thread", "threadName",
}


def test_the_reserved_names_are_what_we_think_they_are():
    """Derived from a real record rather than trusted from a list. @verifies REQ-0034"""
    record = logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None)
    assert set(vars(record)) - {"message", "asctime"} <= RESERVED


def log_extras() -> list[tuple[str, int, str]]:
    """Every `extra={...}` key passed to a logging call under `src/`."""
    found: list[tuple[str, int, str]] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        found.append(
                            (str(path.relative_to(SRC)), node.lineno, key.value)
                        )
    return found


def test_the_scan_finds_the_log_calls_at_all():
    """A guard that silently matches nothing is not a guard. @verifies REQ-0034"""
    assert len(log_extras()) > 5


def test_no_log_call_shadows_a_reserved_record_attribute():
    """No `extra` key may collide with an attribute `logging` owns.

    A collision raises `KeyError` from the logging call itself — which, inside an
    `except` block, takes down the handler that was meant to contain the problem. This
    scan is cheap and the failure mode is not, so it is checked rather than remembered.

    @verifies REQ-0034
    """
    offenders = [
        f"{path}:{line} passes extra={{{key!r}: ...}}"
        for path, line, key in log_extras()
        if key in RESERVED
    ]
    assert offenders == []


def test_a_context_filter_supplies_the_fields_the_formatter_demands():
    """The formatter interpolates `request_id` and `user_id` unconditionally, so a
    record made anywhere else — a library's, say — would raise on format without this.

    @verifies REQ-0034
    """
    from celine.assistant.logging_ import DefaultContextFilter

    record = logging.LogRecord("lib", logging.INFO, "p", 1, "m", None, None)
    assert DefaultContextFilter().filter(record) is True
    assert record.request_id == "-"
    assert record.user_id == "-"


# @verifies REQ-0034
def test_the_filter_leaves_a_supplied_value_alone():
    from celine.assistant.logging_ import DefaultContextFilter

    record = logging.LogRecord("lib", logging.INFO, "p", 1, "m", None, None)
    record.user_id = "alice"

    DefaultContextFilter().filter(record)
    assert record.user_id == "alice"
