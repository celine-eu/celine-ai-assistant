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
from sqlalchemy import func, select
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
    ) -> str:
        async with self._session() as session:
            async with session.begin():
                msg = Message(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role=role,
                    content=content,
                    created_at=int(time.time()),
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
        self, user_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        async with self._session() as session:
            stmt = (
                select(Attachment)
                .where(
                    (Attachment.scope == "system")
                    | (
                        (Attachment.scope == "user")
                        & (Attachment.owner_user_id == user_id)
                    )
                )
                .order_by(Attachment.created_at.desc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_att_dict(a) for a in rows]

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
        "uri": att.uri,
        "path": att.path,
        "filename": att.filename,
        "content_type": att.content_type,
        "size_bytes": att.size_bytes,
        "caption": att.caption,
        "ocr_text": att.ocr_text,
        "created_at": att.created_at,
    }
