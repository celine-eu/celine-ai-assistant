from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .settings import settings

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
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                  conversation_id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  created_at INTEGER NOT NULL
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                  id TEXT PRIMARY KEY,
                  conversation_id TEXT NOT NULL,
                  user_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  created_at INTEGER NOT NULL,
                  FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
                );
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);"
            )
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
                    return Conversation(conversation_id=row[0])

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
            return await asyncio.to_thread(self._list, user_id, conversation_id, limit)

    def _list(
        self, user_id: str, conversation_id: str, limit: int
    ) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT role, content, created_at FROM messages WHERE user_id=? AND conversation_id=? ORDER BY created_at ASC LIMIT ?",
                (user_id, conversation_id, int(limit)),
            ).fetchall()
            return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]
        finally:
            con.close()
