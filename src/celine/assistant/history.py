from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Conversation:
    conversation_id: str


class HistoryStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def _column_exists(self, con: sqlite3.Connection, table: str, column: str) -> bool:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations(
                    conversation_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS messages(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS attachments(
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,                 -- 'user' | 'system'
                    owner_user_id TEXT,                  -- NULL for system, user_id for user scope
                    uri TEXT NOT NULL,
                    path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    size_bytes INTEGER NOT NULL,
                    caption TEXT,                        -- vision caption/description
                    ocr_text TEXT,                       -- optional extracted text
                    created_at INTEGER NOT NULL
                )
                """
            )

            if not self._column_exists(con, "attachments", "scope"):
                con.execute(
                    "ALTER TABLE attachments ADD COLUMN scope TEXT NOT NULL DEFAULT 'user'"
                )
            if not self._column_exists(con, "attachments", "owner_user_id"):
                con.execute("ALTER TABLE attachments ADD COLUMN owner_user_id TEXT")
            if not self._column_exists(con, "attachments", "caption"):
                con.execute("ALTER TABLE attachments ADD COLUMN caption TEXT")
            if not self._column_exists(con, "attachments", "ocr_text"):
                con.execute("ALTER TABLE attachments ADD COLUMN ocr_text TEXT")

            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_att_owner ON attachments(owner_user_id)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_att_scope ON attachments(scope)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_att_created ON attachments(created_at)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id)")

            con.commit()
        finally:
            con.close()

    async def get_or_create_conversation(
        self, user_id: str, conversation_id: str | None
    ) -> Conversation:
        async with self._lock:
            return await asyncio.to_thread(
                self._get_or_create, user_id, conversation_id
            )

    def _get_or_create(self, user_id: str, conversation_id: str | None) -> Conversation:
        con = self._connect()
        try:
            if conversation_id:
                row = con.execute(
                    "SELECT conversation_id FROM conversations WHERE conversation_id=? AND user_id=?",
                    (conversation_id, user_id),
                ).fetchone()
                if row:
                    return Conversation(conversation_id=conversation_id)

            cid = conversation_id or str(uuid.uuid4())
            con.execute(
                "INSERT OR IGNORE INTO conversations(conversation_id, user_id, created_at) VALUES(?,?,?)",
                (cid, user_id, int(time.time())),
            )
            con.commit()
            return Conversation(conversation_id=cid)
        finally:
            con.close()

    async def append_message(
        self, user_id: str, conversation_id: str, role: str, content: str
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._append, user_id, conversation_id, role, content
            )

    def _append(
        self, user_id: str, conversation_id: str, role: str, content: str
    ) -> None:
        con = self._connect()
        try:
            con.execute(
                "INSERT INTO messages(id, conversation_id, user_id, role, content, created_at) VALUES(?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    conversation_id,
                    user_id,
                    role,
                    content,
                    int(time.time()),
                ),
            )
            con.commit()
        finally:
            con.close()

    async def list_messages(
        self, user_id: str, conversation_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(
                self._list_messages, user_id, conversation_id, limit
            )

    def _list_messages(
        self, user_id: str, conversation_id: str, limit: int
    ) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE user_id=? AND conversation_id=?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (user_id, conversation_id, int(limit)),
            ).fetchall()
            return [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        finally:
            con.close()

    async def list_conversations(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(
                self._list_conversations, user_id, limit, offset
            )

    def _list_conversations(
        self, user_id: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT
                    c.conversation_id,
                    c.created_at,
                    COALESCE(
                        (SELECT MAX(m.created_at) FROM messages m
                         WHERE m.user_id=c.user_id AND m.conversation_id=c.conversation_id),
                        c.created_at
                    ) AS last_message_at,
                    (SELECT COUNT(1) FROM messages m
                     WHERE m.user_id=c.user_id AND m.conversation_id=c.conversation_id) AS message_count,
                    (SELECT SUBSTR(m.content, 1, 140) FROM messages m
                     WHERE m.user_id=c.user_id AND m.conversation_id=c.conversation_id
                     ORDER BY m.created_at DESC LIMIT 1) AS last_snippet
                FROM conversations c
                WHERE c.user_id=?
                ORDER BY last_message_at DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, int(limit), int(offset)),
            ).fetchall()
            return [
                {
                    "conversation_id": r["conversation_id"],
                    "created_at": r["created_at"],
                    "last_message_at": r["last_message_at"],
                    "message_count": r["message_count"],
                    "last_snippet": r["last_snippet"],
                }
                for r in rows
            ]
        finally:
            con.close()

    async def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self._delete_conversation, user_id, conversation_id
            )

    def _delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        con = self._connect()
        try:
            row = con.execute(
                "SELECT 1 FROM conversations WHERE conversation_id=? AND user_id=?",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return False
            con.execute(
                "DELETE FROM messages WHERE conversation_id=? AND user_id=?",
                (conversation_id, user_id),
            )
            con.execute(
                "DELETE FROM conversations WHERE conversation_id=? AND user_id=?",
                (conversation_id, user_id),
            )
            con.commit()
            return True
        finally:
            con.close()

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
        async with self._lock:
            return await asyncio.to_thread(
                self._record_attachment,
                scope,
                owner_user_id,
                uri,
                path,
                filename,
                content_type,
                size_bytes,
                caption,
                ocr_text,
            )

    def _record_attachment(
        self,
        scope: str,
        owner_user_id: str | None,
        uri: str,
        path: str,
        filename: str,
        content_type: str | None,
        size_bytes: int,
        caption: str | None,
        ocr_text: str | None,
    ) -> str:
        con = self._connect()
        try:
            att_id = str(uuid.uuid4())
            con.execute(
                """
                INSERT INTO attachments(id, scope, owner_user_id, uri, path, filename, content_type, size_bytes, caption, ocr_text, created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    att_id,
                    scope,
                    owner_user_id,
                    uri,
                    path,
                    filename,
                    content_type,
                    int(size_bytes),
                    caption,
                    ocr_text,
                    int(time.time()),
                ),
            )
            con.commit()
            return att_id
        finally:
            con.close()

    async def list_attachments_for_user(
        self, user_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(
                self._list_attachments_for_user, user_id, limit
            )

    def _list_attachments_for_user(
        self, user_id: str, limit: int
    ) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT id, scope, owner_user_id, uri, path, filename, content_type, size_bytes, caption, ocr_text, created_at
                FROM attachments
                WHERE scope='system' OR (scope='user' AND owner_user_id=?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    async def get_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return await asyncio.to_thread(self._get_attachment_any, attachment_id)

    def _get_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        con = self._connect()
        try:
            r = con.execute(
                """
                SELECT id, scope, owner_user_id, uri, path, filename, content_type, size_bytes, caption, ocr_text, created_at
                FROM attachments
                WHERE id=?
                """,
                (attachment_id,),
            ).fetchone()
            return dict(r) if r else None
        finally:
            con.close()

    async def delete_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return await asyncio.to_thread(self._delete_attachment_any, attachment_id)

    def _delete_attachment_any(self, attachment_id: str) -> dict[str, Any] | None:
        con = self._connect()
        try:
            row = con.execute(
                """
                SELECT id, scope, owner_user_id, uri, path, filename, content_type, size_bytes, caption, ocr_text, created_at
                FROM attachments
                WHERE id=?
                """,
                (attachment_id,),
            ).fetchone()
            if not row:
                return None
            con.execute("DELETE FROM attachments WHERE id=?", (attachment_id,))
            con.commit()
            return dict(row)
        finally:
            con.close()
