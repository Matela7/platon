"""SQLite conversation history and sidebar metadata, independent of agent policies."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app_logging import LOGGER, log_call

class ConversationStore:
    def __init__(self, path: Path):
        LOGGER.info("Opening conversation store")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.checkpointer.setup()
        self.connection.execute("CREATE TABLE IF NOT EXISTS threads (thread_id TEXT PRIMARY KEY, messages_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
        self.connection.commit()
        LOGGER.info("Conversation store ready")

    def latest(self):
        row = self.connection.execute("SELECT thread_id FROM threads ORDER BY updated_at DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def ensure(self, thread_id):
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute("INSERT OR IGNORE INTO threads VALUES (?, ?, ?, ?)", (thread_id, "[]", now, now))
        self.connection.commit()

    def exists(self, thread_id):
        return self.connection.execute("SELECT 1 FROM threads WHERE thread_id = ?", (thread_id,)).fetchone() is not None

    @log_call
    def load(self, thread_id):
        row = self.connection.execute("SELECT messages_json FROM threads WHERE thread_id = ?", (thread_id,)).fetchone()
        return self._decode(row[0]) if row else []

    @staticmethod
    def _decode(raw):
        try:
            messages = json.loads(raw)
            return messages if isinstance(messages, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    @log_call
    def save(self, thread_id, messages):
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute("UPDATE threads SET messages_json = ?, updated_at = ? WHERE thread_id = ?", (json.dumps(messages, ensure_ascii=False), now, thread_id))
        self.connection.commit()
        LOGGER.info("Conversation history persisted (message_count=%d)", len(messages))

    @log_call
    def list(self):
        rows = self.connection.execute("SELECT thread_id, messages_json, created_at, updated_at FROM threads ORDER BY updated_at DESC").fetchall()
        result = []
        for thread_id, raw, created, updated in rows:
            messages = self._decode(raw)
            title = next((m["content"] for m in messages if m.get("role") == "user"), "New conversation")
            title = " ".join(title.split())
            result.append({"thread_id": thread_id, "title": title[:61] + "..." if len(title) > 64 else title,
                           "message_count": len(messages), "created_at": created, "updated_at": updated})
        return result

    def close(self):
        self.connection.close()
        LOGGER.info("Conversation store closed")
