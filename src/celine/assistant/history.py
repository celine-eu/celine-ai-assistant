"""Chat history persistence backed by SQLAlchemy (async).

Conversations, messages and attachment records. The store is instantiated once in the
application lifespan and reached from a route through `get_history_store`.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import AsyncSessionLocal, Attachment, Conversation, Message

log = logging.getLogger(__name__)


class HistoryStore:
    """Async history store built on SQLAlchemy.

    Instantiate once at application startup::

        store = HistoryStore()

    All public methods are async and safe for concurrent use — SQLAlchemy's async
    session handles connection pooling internally.

    `session_factory` defaults to the application's, configured at import in
    `db/engine.py`. Passing one is how a test points the store at its own database; it
    is the only seam, because every method opens its own session and none takes one.
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        self._session = session_factory or AsyncSessionLocal

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def get_or_create_conversation(
        self,
        user_id: str,
        conversation_id: str | None = None,
    ) -> Conversation:
        async with self._session() as session:
            async with session.begin():
                if conversation_id:
                    result = await session.execute(
                        select(Conversation).where(
                            Conversation.conversation_id == conversation_id,
                            Conversation.user_id == user_id,
                        )
                    )
                    conv = result.scalar_one_or_none()
                    if conv:
                        return conv

                conv = Conversation(
                    conversation_id=conversation_id or str(uuid.uuid4()),
                    user_id=user_id,
                    created_at=int(time.time()),
                )
                session.add(conv)
            return conv

    async def list_conversations(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._session() as session:
            # last_message_at subquery
            last_msg_at = (
                select(func.max(Message.created_at))
                .where(Message.conversation_id == Conversation.conversation_id)
                .correlate(Conversation)
                .scalar_subquery()
            )
            msg_count = (
                select(func.count(Message.id))
                .where(Message.conversation_id == Conversation.conversation_id)
                .correlate(Conversation)
                .scalar_subquery()
            )
            # last_snippet: grab the most recent message content (first 120 chars)
            last_snippet_sq = (
                select(Message.content)
                .where(Message.conversation_id == Conversation.conversation_id)
                .correlate(Conversation)
                .order_by(Message.created_at.desc())
                .limit(1)
                .scalar_subquery()
            )

            stmt = (
                select(
                    Conversation.conversation_id,
                    Conversation.created_at,
                    last_msg_at.label("last_message_at"),
                    msg_count.label("message_count"),
                    last_snippet_sq.label("last_snippet"),
                )
                .where(Conversation.user_id == user_id)
                .order_by(last_msg_at.desc())
                .limit(limit)
                .offset(offset)
            )

            rows = (await session.execute(stmt)).all()
            return [
                {
                    "conversation_id": r.conversation_id,
                    "created_at": r.created_at,
                    "last_message_at": r.last_message_at,
                    "message_count": r.message_count,
                    "last_snippet": (r.last_snippet or "")[:120],
                }
                for r in rows
            ]

    async def conversation_exists(self, user_id: str, conversation_id: str) -> bool:
        """Whether this user owns this conversation.

        One indexed lookup. Without it the route had to page through the caller's most
        recent conversations and call anything past the end missing.
        """
        async with self._session() as session:
            result = await session.execute(
                select(Conversation.conversation_id).where(
                    Conversation.conversation_id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            return result.scalar_one_or_none() is not None

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        async with self._session() as session:
            async with session.begin():
                result = await session.execute(
                    select(Conversation).where(
                        Conversation.conversation_id == conversation_id,
                        Conversation.user_id == user_id,
                    )
                )
                conv = result.scalar_one_or_none()
                if not conv:
                    return False
                await session.delete(conv)
            return True

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def append_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        *,
        trace: dict[str, Any] | None = None,
    ) -> str:
        """Store one message. `trace` is what produced an `assistant` message
        (REQ-0053); it is written with the row and never listed by `list_messages`."""
        async with self._session() as session:
            async with session.begin():
                msg = Message(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role=role,
                    content=content,
                    created_at=int(time.time()),
                    trace=trace,
                )
                session.add(msg)
            return msg.id

    async def list_messages(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        async with self._session() as session:
            stmt = (
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.user_id == user_id,
                )
                .order_by(Message.created_at.asc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": m.id,
                    "conversation_id": m.conversation_id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at,
                }
                for m in rows
            ]

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    async def record_attachment(
        self,
        *,
        scope: str,
        owner_user_id: str | None,
        community_id: str | None,
        uri: str,
        path: str,
        filename: str,
        content_type: str | None,
        size_bytes: int,
        caption: str | None = None,
        ocr_text: str | None = None,
    ) -> str:
        async with self._session() as session:
            async with session.begin():
                att = Attachment(
                    id=str(uuid.uuid4()),
                    scope=scope,
                    owner_user_id=owner_user_id,
                    community_id=community_id,
                    uri=uri,
                    path=path,
                    filename=filename,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    caption=caption,
                    ocr_text=ocr_text,
                    created_at=int(time.time()),
                )
                session.add(att)
            return att.id

    async def list_attachments_for_user(
        self, user_id: str, community_id: str | None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """The caller's own uploads, and what was shared with their community."""
        async with self._session() as session:
            own = (Attachment.scope == "user") & (Attachment.owner_user_id == user_id)
            shared = (
                (Attachment.scope == "system")
                & (Attachment.community_id == community_id)
                if community_id
                else None
            )
            stmt = (
                select(Attachment)
                .where(own if shared is None else (own | shared))
                .order_by(Attachment.created_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_att_dict(a) for a in rows]

    async def list_attachments_for_community(
        self, community_id: str
    ) -> list[dict[str, Any]]:
        """Every attachment a community's knowledge base indexes, oldest first."""
        async with self._session() as session:
            stmt = (
                select(Attachment)
                .where(Attachment.community_id == community_id)
                .order_by(Attachment.created_at.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_att_dict(a) for a in rows]

    async def update_attachment_text(
        self, attachment_id: str, *, ocr_text: str | None, caption: str | None
    ) -> None:
        """Replace what extraction produced, after it ran again."""
        async with self._session() as session:
            async with session.begin():
                await session.execute(
                    update(Attachment)
                    .where(Attachment.id == attachment_id)
                    .values(ocr_text=ocr_text, caption=caption)
                )

    async def attachment_communities(self) -> list[str]:
        async with self._session() as session:
            stmt = (
                select(Attachment.community_id)
                .where(Attachment.community_id.is_not(None))
                .distinct()
            )
            return sorted((await session.execute(stmt)).scalars().all())

    async def count_attachments_without_community(self) -> int:
        async with self._session() as session:
            stmt = select(func.count(Attachment.id)).where(
                Attachment.community_id.is_(None)
            )
            return int((await session.execute(stmt)).scalar_one())

    async def assign_community_to_unassigned(self, community_id: str) -> int:
        """Give every attachment that has no community this one. Returns how many."""
        async with self._session() as session:
            async with session.begin():
                result = await session.execute(
                    update(Attachment)
                    .where(Attachment.community_id.is_(None))
                    .values(community_id=community_id)
                )
            return int(result.rowcount or 0)

    async def get_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            result = await session.execute(
                select(Attachment).where(Attachment.id == attachment_id)
            )
            att = result.scalar_one_or_none()
            return _att_dict(att) if att else None

    async def delete_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        async with self._session() as session:
            async with session.begin():
                result = await session.execute(
                    select(Attachment).where(Attachment.id == attachment_id)
                )
                att = result.scalar_one_or_none()
                if not att:
                    return None
                data = _att_dict(att)
                await session.delete(att)
            return data

    # ------------------------------------------------------------------
    # Erasure and retention (REQ-0057..0059). `erasure.py` drives these;
    # an attachment's file and vectors are deleted there, not here.
    # ------------------------------------------------------------------

    async def delete_conversations_of(self, user_id: str) -> dict[str, int]:
        """Delete every conversation of `user_id` and every message stored under it.

        Messages are deleted by their own `user_id` as well as by conversation, so none
        survives in a conversation the person does not own. Returns the counts.
        """
        async with self._session() as session:
            async with session.begin():
                owned = select(Conversation.conversation_id).where(
                    Conversation.user_id == user_id
                )
                messages = await session.execute(
                    delete(Message).where(
                        or_(Message.user_id == user_id, Message.conversation_id.in_(owned))
                    )
                )
                conversations = await session.execute(
                    delete(Conversation).where(Conversation.user_id == user_id)
                )
            return {
                "conversations": int(conversations.rowcount or 0),
                "messages": int(messages.rowcount or 0),
            }

    async def attachments_owned_by(self, user_id: str) -> list[dict[str, Any]]:
        """Every `user`-scope attachment of `user_id`, unbounded, oldest first."""
        async with self._session() as session:
            stmt = (
                select(Attachment)
                .where(Attachment.scope == "user", Attachment.owner_user_id == user_id)
                .order_by(Attachment.created_at.asc())
            )
            return [_att_dict(a) for a in (await session.execute(stmt)).scalars().all()]

    async def delete_idle_conversations(
        self, before: int, *, dry_run: bool = False
    ) -> dict[str, int]:
        """Delete each conversation whose newest message (or, with none, its creation)
        is older than `before`, with its messages. Returns the counts, also when
        `dry_run` deletes nothing."""
        newest = (
            select(
                Message.conversation_id.label("conversation_id"),
                func.max(Message.created_at).label("newest"),
            )
            .group_by(Message.conversation_id)
            .subquery()
        )
        idle = select(Conversation.conversation_id).outerjoin(
            newest, newest.c.conversation_id == Conversation.conversation_id
        ).where(func.coalesce(newest.c.newest, Conversation.created_at) < before)

        conversations = messages = 0
        async with self._session() as session, session.begin():
            ids = list((await session.execute(idle)).scalars().all())
            for chunk in _chunks(ids):
                conversations += len(chunk)
                if dry_run:
                    counted = await session.execute(
                        select(func.count(Message.id)).where(
                            Message.conversation_id.in_(chunk)
                        )
                    )
                    messages += int(counted.scalar_one())
                    continue
                result = await session.execute(
                    delete(Message).where(Message.conversation_id.in_(chunk))
                )
                messages += int(result.rowcount or 0)
                await session.execute(
                    delete(Conversation).where(Conversation.conversation_id.in_(chunk))
                )
        return {"conversations": conversations, "messages": messages}

    async def idle_attachments(self, before: int) -> list[dict[str, Any]]:
        """`user`-scope attachments uploaded before `before` and not used since.

        A use is an answer to the attachment's owner, stored at or after `before`, whose
        trace (REQ-0053) lists it among the turn's attachments or as the
        `attachment_id` of a retrieved source.
        """
        async with self._session() as session:
            candidates = (
                (
                    await session.execute(
                        select(Attachment).where(
                            Attachment.scope == "user", Attachment.created_at < before
                        )
                    )
                )
                .scalars()
                .all()
            )
            owners = sorted({a.owner_user_id for a in candidates if a.owner_user_id})
            used: set[tuple[str, str]] = set()
            for chunk in _chunks(owners):
                rows = await session.execute(
                    select(Message.user_id, Message.trace).where(
                        Message.user_id.in_(chunk),
                        Message.role == "assistant",
                        Message.created_at >= before,
                    )
                )
                for user_id, trace in rows.all():
                    used.update((user_id, att_id) for att_id in _used_attachments(trace))
            return [
                _att_dict(a) for a in candidates if (a.owner_user_id, a.id) not in used
            ]

    async def existing_attachment_ids(self, attachment_ids: list[str]) -> set[str]:
        """Those of `attachment_ids` that still have a row."""
        found: set[str] = set()
        async with self._session() as session:
            for chunk in _chunks(sorted(set(attachment_ids))):
                result = await session.execute(
                    select(Attachment.id).where(Attachment.id.in_(chunk))
                )
                found.update(result.scalars().all())
        return found


# Under asyncpg's limit of bind parameters per statement, with room to spare.
_CHUNK = 1000


def _chunks(values: list[str]) -> list[list[str]]:
    return [values[i : i + _CHUNK] for i in range(0, len(values), _CHUNK)]


def _used_attachments(trace: Any) -> set[str]:
    """The attachment ids one stored answer's trace says it used."""
    if not isinstance(trace, dict):
        return set()
    ids = {a for a in trace.get("attachments") or [] if isinstance(a, str)}
    for source in trace.get("sources") or []:
        if isinstance(source, dict) and isinstance(source.get("attachment_id"), str):
            ids.add(source["attachment_id"])
    return ids


def get_history_store(request: Request) -> HistoryStore:
    """The store, as a dependency.

    The instance still lives on `app.state`, set by the lifespan — this is the seam that
    lets a test replace it with `app.dependency_overrides[get_history_store]`, the same
    mechanism `../dataset-api` uses for its sessions. Routes declare it rather than
    reaching through `request.app.state`, so what a route touches is visible in its
    signature.
    """
    return request.app.state.history_store


def _att_dict(att: Attachment) -> dict[str, Any]:
    return {
        "id": att.id,
        "scope": att.scope,
        "owner_user_id": att.owner_user_id,
        "community_id": att.community_id,
        "uri": att.uri,
        "path": att.path,
        "filename": att.filename,
        "content_type": att.content_type,
        "size_bytes": att.size_bytes,
        "caption": att.caption,
        "ocr_text": att.ocr_text,
        "created_at": att.created_at,
    }
