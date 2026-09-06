"""Conversation orchestration, runtime configuration, and persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    trim_messages,
)
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.agents.supervisor_agent import SupervisorAgent
from agent.base_agent import BaseAgent
from agent.models.agent_config import AgentConfig
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig

HistoryItem = dict[str, str] | BaseMessage
MessageHistory = list[HistoryItem]
ConversationSummary = dict[str, str | int]

_CHECKPOINT_THREAD_PREFIX = "platon-chat-v2:"


class AgentOrchestrator:
    """Run a top-level agent and own conversation persistence."""

    def __init__(
        self,
        config: AgentOrchestratorConfig | None = None,
        agent_config: AgentConfig | None = None,
        agent: BaseAgent | None = None,
        thread_id: str | None = None,
    ) -> None:
        """Initialize the selected concrete agent and thread persistence.

        Args:
            config: Infrastructure settings propagated to the concrete agent.
            agent_config: Behavior settings propagated to the concrete agent.
            agent: Optional prebuilt top-level agent for dependency injection.
            thread_id: Optional stable id of the persisted conversation.
        """
        self.config = config or AgentOrchestratorConfig()
        self.agent_config = agent_config or AgentConfig()
        self.sqlite_path = (
            Path(self.config.sqlite_path)
            if self.config.sqlite_path is not None
            else self.config.working_dir / "agent_threads.sqlite3"
        )
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_connection = sqlite3.connect(
            self.sqlite_path,
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self._sqlite_connection)
        self.checkpointer.setup()
        self._init_sqlite()
        self.thread_id = thread_id or self._latest_thread_id() or str(uuid4())
        self._ensure_thread()
        self.agent = agent or SupervisorAgent.from_config(
            agent_config=self.agent_config,
            runtime_config=self.config,
            checkpointer=self.checkpointer,
        )
        if not isinstance(self.agent, BaseAgent):
            raise TypeError("agent must inherit from BaseAgent")
        if self.agent.checkpointer is None:
            self.agent.checkpointer = self.checkpointer

    def _init_sqlite(self) -> None:
        """Create the thread persistence table when it does not exist."""
        self._sqlite_connection.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                messages_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._sqlite_connection.commit()

    def _latest_thread_id(self) -> str | None:
        """Return the most recently updated visible conversation, if any."""
        row = self._sqlite_connection.execute(
            "SELECT thread_id FROM threads ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return row[0] if row is not None else None

    def _ensure_thread(self) -> None:
        """Make a new empty conversation visible before its first message."""
        now = datetime.now(timezone.utc).isoformat()
        self._sqlite_connection.execute(
            """
            INSERT OR IGNORE INTO threads (
                thread_id, messages_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (self.thread_id, "[]", now, now),
        )
        self._sqlite_connection.commit()

    @staticmethod
    def _message_from_history_item(message: HistoryItem) -> BaseMessage | None:
        """Convert one stored history entry to a LangChain message."""
        if isinstance(message, BaseMessage):
            if isinstance(message, SystemMessage):
                return None
            return message
        if not isinstance(message, dict):
            return None

        content = message.get("content")
        if not isinstance(content, str) or not (content := content.strip()):
            return None

        match message.get("role"):
            case "user":
                return HumanMessage(content=content)
            case "assistant":
                return AIMessage(content=content)
            case "system":
                return None
            case _:
                return None

    def _prepare_messages(
        self, user_input: str, history: MessageHistory | None
    ) -> list[BaseMessage]:
        """Normalize, trim, and append the current user input."""
        messages = [
            normalized
            for item in history or []
            if (normalized := self._message_from_history_item(item)) is not None
        ]
        messages = trim_messages(
            messages,
            max_tokens=self.agent_config.max_history_messages,
            token_counter=len,
            strategy="last",
            include_system=True,
            start_on="human",
        )
        messages.append(HumanMessage(content=user_input))
        return messages

    @staticmethod
    def _content_to_text(content: Any) -> str | None:
        """Extract normalized plain text from a LangChain content value."""
        if isinstance(content, str):
            return content.strip() or None
        if not isinstance(content, list):
            return None

        parts = [
            item if isinstance(item, str) else item.get("text", "")
            for item in content
            if isinstance(item, (str, dict))
        ]
        text = "\n".join(part.strip() for part in parts if part.strip()).strip()
        return text or None

    def _extract_answer(self, result: dict[str, Any]) -> str:
        """Extract the most recent assistant text response from agent output."""
        for message in reversed(result.get("messages", [])):
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                if message.get("role") != "assistant":
                    continue
                content = message.get("content")
            elif getattr(message, "type", None) != "ai":
                continue

            if answer := self._content_to_text(content):
                return answer
        return ""

    def _serialize_messages(
        self, messages: MessageHistory
    ) -> list[dict[str, str]]:
        """Serialize supported LangChain messages for SQLite storage."""
        serialized: list[dict[str, str]] = []
        for message in messages:
            normalized = self._message_from_history_item(message)
            if normalized is None:
                continue

            role = (
                "user" if isinstance(normalized, HumanMessage)
                else "assistant" if isinstance(normalized, AIMessage)
                else "system" if isinstance(normalized, SystemMessage)
                else None
            )
            content = self._content_to_text(normalized.content)
            if role is not None and content is not None:
                serialized.append({"role": role, "content": content})
        return serialized

    def _save_thread(self, messages: MessageHistory) -> None:
        """Persist the complete conversation for the current thread."""
        serialized = self._serialize_messages(messages)
        now = datetime.now(timezone.utc).isoformat()
        self._sqlite_connection.execute(
            """
            INSERT INTO threads (thread_id, messages_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                messages_json = excluded.messages_json,
                updated_at = excluded.updated_at
            """,
            (self.thread_id, json.dumps(serialized), now, now),
        )
        self._sqlite_connection.commit()

    def load_thread_history(self) -> MessageHistory:
        """Load the visible history for the current conversation."""
        row = self._sqlite_connection.execute(
            "SELECT messages_json FROM threads WHERE thread_id = ?",
            (self.thread_id,),
        ).fetchone()
        if row is None:
            return []
        try:
            messages = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return []
        return messages if isinstance(messages, list) else []

    def thread_exists(self, thread_id: str) -> bool:
        """Return whether a visible conversation has the exact supplied id."""
        row = self._sqlite_connection.execute(
            "SELECT 1 FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _conversation_title(messages: MessageHistory) -> str:
        """Build a short sidebar title from the first user message."""
        for message in messages:
            normalized = AgentOrchestrator._message_from_history_item(message)
            if not isinstance(normalized, HumanMessage):
                continue
            if content := AgentOrchestrator._content_to_text(normalized.content):
                title = " ".join(content.split())
                return title if len(title) <= 64 else f"{title[:61]}..."
        return "New conversation"

    def list_threads(self) -> list[ConversationSummary]:
        """List all persisted conversations for the history sidebar."""
        rows = self._sqlite_connection.execute(
            """
            SELECT thread_id, messages_json, created_at, updated_at
            FROM threads
            ORDER BY updated_at DESC
            """
        ).fetchall()
        conversations: list[ConversationSummary] = []
        for thread_id, raw_messages, created_at, updated_at in rows:
            try:
                messages = json.loads(raw_messages)
            except (TypeError, json.JSONDecodeError):
                messages = []
            if not isinstance(messages, list):
                messages = []
            conversations.append(
                {
                    "thread_id": thread_id,
                    "title": self._conversation_title(messages),
                    "message_count": len(messages),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return conversations

    def _checkpoint_config(self) -> dict[str, Any]:
        """Return the stable checkpoint identity for this conversation."""
        return {
            "configurable": {
                "thread_id": f"{_CHECKPOINT_THREAD_PREFIX}{self.thread_id}",
            }
        }

    def _has_checkpoint(self) -> bool:
        """Return whether the corrected checkpoint namespace has state."""
        return self.checkpointer.get_tuple(self._checkpoint_config()) is not None

    def close(self) -> None:
        """Close the SQLite connection owned by this orchestrator."""
        self._sqlite_connection.close()

    def invoke(
        self, user_input: str, history: MessageHistory | None = None
    ) -> dict[str, Any]:
        """Invoke the selected agent and persist the resulting thread state."""
        user_input = user_input.strip()
        if not user_input:
            raise ValueError("user_input must not be empty")

        started_at = perf_counter()
        run_id = str(uuid4())
        visible_history: MessageHistory = [*(history or [])]
        messages = (
            [HumanMessage(content=user_input)]
            if self._has_checkpoint()
            else self._prepare_messages(user_input, visible_history)
        )
        checkpoint_config = self._checkpoint_config()
        result = self.agent.create_agent().invoke(
            {"messages": messages},
            config={
                "run_name": "agent_orchestrator_invoke",
                "tags": ["platon", "orchestrator", self.agent.model_name],
                **checkpoint_config,
                "metadata": {
                    "run_id": run_id,
                    "agent": type(self.agent).__name__,
                    "model": self.agent.model_name,
                    "thread_id": self.thread_id,
                    "history_messages": len(visible_history),
                    "persist_dir": self.config.persist_dir,
                },
            },
        )
        answer = self._extract_answer(result)
        thread_messages: MessageHistory = [*visible_history]
        thread_messages.append({"role": "user", "content": user_input})
        if answer:
            thread_messages.append({"role": "assistant", "content": answer})
        self._save_thread(thread_messages)

        return {
            "run_id": run_id,
            "answer": answer,
            "result": result,
            "messages": messages,
            "thread_id": self.thread_id,
            "elapsed_seconds": round(perf_counter() - started_at, 3),
        }
