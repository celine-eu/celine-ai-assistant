"""Erasure and retention: deleting a member's data completely, on request or with age.

REQ-0056..0059 (`docs/specifications/erasure.md`). The service functions here are what
`celine-assistant erase-subject`, `retention run` and `kb orphans` run, and
`POST /admin/subjects/erase` calls the first. Which service asks for a person's erasure
across the platform is not decided; this is the assistant's own part of it.

Every attachment goes through `delete_attachment`, so a member's own delete, an erasure
and retention leave the same nothing behind.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import rag
from .auth import UserIdentity, get_user_identity
from .history import HistoryStore, get_history_store
from .settings import settings
from .uploads import delete_upload, storage_reachable

log = logging.getLogger(__name__)

#: The scope `POST /admin/subjects/erase` requires in the verified token's `scope` claim.
ERASE_SCOPE = "assistant.subject.erase"


class AttachmentNotDeleted(RuntimeError):
    """One attachment could not be deleted completely. Its row is still there, so the
    same delete can be run again."""

    def __init__(self, attachment_id: str) -> None:
        super().__init__(f"attachment {attachment_id} was not deleted; retry")
        self.attachment_id = attachment_id


# --- REQ-0056 -------------------------------------------------------------------------


async def delete_attachment(history: HistoryStore, att: dict[str, Any]) -> dict[str, int]:
    """Delete one attachment's vectors everywhere, then its file, then its row.

    The row goes last: if anything before it fails, the row is what lets the delete be
    found and repeated. Repeating a delete that already succeeded in part is harmless.
    Returns how many vectors and files were removed.
    """
    if att.get("path") and not await storage_reachable():
        log.error("attachment_delete_without_storage", extra={"attachment": att["id"]})
        raise AttachmentNotDeleted(att["id"])
    try:
        vectors = await asyncio.to_thread(
            rag.delete_everywhere, {"attachment_id": att["id"]}
        )
        removed_file = bool(att.get("path")) and await delete_upload(att["path"])
        await history.delete_attachment_any(att["id"])
    except Exception as exc:
        log.exception("attachment_delete_failed", extra={"attachment": att["id"]})
        raise AttachmentNotDeleted(att["id"]) from exc
    return {"vectors": sum(vectors.values()), "files": int(removed_file)}


async def _delete_attachments(
    history: HistoryStore, attachments: list[dict[str, Any]], report: dict[str, Any]
) -> None:
    for att in attachments:
        try:
            removed = await delete_attachment(history, att)
        except AttachmentNotDeleted:
            report["failed"].append(att["id"])
            continue
        report["attachments"] += 1
        report["files"] += removed["files"]
        report["vectors"] += removed["vectors"]


# --- REQ-0057 -------------------------------------------------------------------------


async def erase_subject(history: HistoryStore, sub: str) -> dict[str, Any]:
    """Delete everything the assistant holds about the person `sub`.

    Their conversations and messages (traces included), their own uploads through
    `delete_attachment`, then any vector still carrying their id that is not shared
    material. Idempotent. Returns the counts per store and what could not be deleted:
    attachment ids, and `"vectors"` when the final vector sweep failed.
    """
    sub = sub.strip()
    if not sub:
        raise ValueError("an empty subject names nobody")

    removed = await history.delete_conversations_of(sub)
    report: dict[str, Any] = {
        "conversations": removed["conversations"],
        "messages": removed["messages"],
        "attachments": 0,
        "files": 0,
        "vectors": 0,
        "failed": [],
    }
    await _delete_attachments(history, await history.attachments_owned_by(sub), report)

    # What a delete left behind before REQ-0056, and legacy points without a scope.
    try:
        swept = await asyncio.to_thread(
            rag.delete_everywhere, {"owner_user_id": sub}, {"scope": "system"}
        )
    except Exception:
        log.exception("subject_vector_sweep_failed")
        report["failed"].append("vectors")
    else:
        report["vectors"] += sum(swept.values())
    return report


# --- REQ-0058 -------------------------------------------------------------------------


def months_before(timestamp: int, months: int) -> int:
    """The same calendar date and time `months` months earlier, in UTC; the last day of
    the month when that month is shorter."""
    t = datetime.fromtimestamp(timestamp, UTC)
    years, month0 = divmod(t.month - 1 - months, 12)
    year, month = t.year + years, month0 + 1
    day = min(t.day, calendar.monthrange(year, month)[1])
    return int(t.replace(year=year, month=month, day=day).timestamp())


async def run_retention(
    history: HistoryStore,
    *,
    months: int | None = None,
    now: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete members' conversations and own attachments idle for `months`
    (`RETENTION_MONTHS` by default). With `dry_run`, count them and delete nothing."""
    months = settings.retention_months if months is None else months
    if months < 1:
        raise ValueError("the retention period is at least one month")
    cutoff = months_before(int(time.time()) if now is None else now, months)

    conversations = await history.delete_idle_conversations(cutoff, dry_run=dry_run)
    idle = await history.idle_attachments(cutoff)
    report: dict[str, Any] = {
        "cutoff": datetime.fromtimestamp(cutoff, UTC).isoformat(),
        "months": months,
        "dry_run": dry_run,
        "conversations": conversations["conversations"],
        "messages": conversations["messages"],
        "attachments": 0,
        "files": 0,
        "vectors": 0,
        "failed": [],
    }
    if dry_run:
        report["attachments"] = len(idle)
    else:
        await _delete_attachments(history, idle, report)
    log.info(
        "retention_run",
        extra={k: v for k, v in report.items() if k != "failed"}
        | {"failed": len(report["failed"])},
    )
    return report


# --- REQ-0059 -------------------------------------------------------------------------


async def orphan_vectors(history: HistoryStore, *, delete: bool = False) -> dict[str, Any]:
    """Vectors whose `attachment_id` has no row, per collection, with how many points
    carry each; deleted when `delete` is set."""
    orphans: dict[str, dict[str, int]] = {}
    for name in await asyncio.to_thread(rag.erasable_collections):
        counts = await asyncio.to_thread(rag.attachment_vector_counts, name)
        known = await history.existing_attachment_ids(list(counts))
        if missing := {i: n for i, n in counts.items() if i not in known}:
            orphans[name] = missing

    deleted = 0
    if delete:
        for name, ids in orphans.items():
            for attachment_id in ids:
                deleted += await asyncio.to_thread(
                    rag.delete_matching, name, {"attachment_id": attachment_id}
                )
    return {
        "orphans": orphans,
        "vectors": sum(sum(ids.values()) for ids in orphans.values()),
        "deleted": deleted,
    }


# --- the administrator route ------------------------------------------------------------

router = APIRouter()


class EraseSubjectRequest(BaseModel):
    sub: str = Field(..., description="The `sub` of the person to erase")

    @field_validator("sub")
    @classmethod
    def _names_someone(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an empty subject names nobody")
        return value.strip()


def _holds_scope(user: UserIdentity, scope: str) -> bool:
    """Whether a verified token grants `scope` (a space-separated string or a list)."""
    if user.raw.get("source") != "jwt-verified":
        return False
    granted = (user.raw.get("claims") or {}).get("scope")
    if isinstance(granted, str):
        return scope in granted.split()
    return isinstance(granted, list) and scope in granted


@router.post("/admin/subjects/erase")
async def erase_subject_route(
    req: EraseSubjectRequest,
    user: Annotated[UserIdentity, Depends(get_user_identity)],
    history_store: Annotated[HistoryStore, Depends(get_history_store)],
):
    """Erase one person (REQ-0057). Requires the scope `assistant.subject.erase`.

    The subject is in the body so that it stays out of access logs, and it is not
    logged here either: the log names the caller and the counts.
    """
    if not _holds_scope(user, ERASE_SCOPE):
        raise HTTPException(status_code=403, detail=f"Requires the scope {ERASE_SCOPE}")

    report = await erase_subject(history_store, req.sub)
    log.info(
        "subject_erased",
        extra={"by": user.user_id}
        | {k: v for k, v in report.items() if k != "failed"}
        | {"failed": len(report["failed"])},
    )
    return JSONResponse(
        status_code=503 if report["failed"] else 200,
        content={"sub": req.sub, **report},
    )
