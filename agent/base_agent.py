from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    trim_messages,
)
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

from agent.models.agent_config import AgentConfig
from agent.prompt_loader import load_prompt
from agent.subagents import create_subagent_tools
from agent.tools.tools import create_default_tools
from vectorstore.client_manager import ClientManager

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

HistoryItem = dict[str, str] | BaseMessage
MessageHistory = list[HistoryItem]


class BaseAgent:
    """Stateful LangChain agent wrapper with SQLite thread persistence.

    The class encapsulates model setup, tool wiring, message normalization,
    invocation metadata and local persistence of user-assistant threads.
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        model: BaseChatModel | None = None,
        tools_list: list[BaseTool] | None = None,
        cm: ClientManager | None = None,
        memory: InMemorySaver | None = None,
        thread_id: str | None = None,
        prompt: str | None = None,
    ) -> None:
        """Initialize the base agent and its runtime dependencies.

        Args:
            config: Optional prebuilt agent config object.
            model: Optional preinitialized chat model.
            tools_list: Optional explicit tools list.
            cm: Optional preinitialized vector store client manager.
            memory: Optional LangGraph checkpointer.
            thread_id: Optional stable thread id for persisted conversation.
            prompt: Optional in-memory system prompt override.
        """
        self.config = config or AgentConfig()

        self.model_name = self.config.model_name
        self.model = model
        self.persist_dir = self.config.persist_dir
        self.tools_list = tools_list
        self.memory = memory or InMemorySaver()
        self.thread_id = thread_id or str(uuid4())
        self.prompt = prompt
        self.working_dir = self.config.working_dir
        self.cm = cm
        self.max_history_messages = self.config.max_history_messages
        self.sqlite_path = (
            Path(self.config.sqlite_path)
            if self.config.sqlite_path is not None
            else self.working_dir / "agent_threads.sqlite3"
        )

        if self.model is None:
            self._setup_model()
        self._init_sqlite()
        if self.tools_list is None:
            self.tools_list = self._setup_tools()

    def _setup_model(self) -> None:
        """Create the default Ollama chat model from runtime config."""
        self.model = ChatOllama(
            model=self.model_name,
            base_url=self.config.base_url,
            keep_alive=self.config.keep_alive,
        )

    def _setup_tools(self) -> list[BaseTool]:
        """Build agent tools by combining search and utility tools.

        Returns:
            Ordered list of tools exposed to the agent.
        """
        if self.cm is None:
            self.cm = ClientManager(persist_dir=self.persist_dir)
        default_tools = create_default_tools(self.cm)
        if self.model is None:
            raise RuntimeError("Agent model must be initialized before its tools.")
        delegation_tools = create_subagent_tools(
            self.model,
            self.cm,
            self.config,
        )
        return [*default_tools, *delegation_tools]

    def _default_prompt(self) -> str:
        """Load the default system prompt defined in configuration."""
        return load_prompt(self.config.system_prompt)

    def _init_sqlite(self) -> None:
        """Create thread persistence table if it does not already exist."""
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    messages_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def create_agent(self, prompt: str | None = None) -> Any:
        """Create a LangChain agent instance for the current settings.

        Args:
            prompt: Optional system prompt override.

        Returns:
            Configured agent object supporting ``invoke``.
        """
        if self.model is None:
            self._setup_model()

        system_prompt = prompt or self.prompt or self._default_prompt()
        self.prompt = system_prompt

        return create_agent(
            model=self.model,
            tools=self.tools_list,
            system_prompt=system_prompt,
            checkpointer=self.memory,
            debug=False,
        )

    def _message_from_history_item(
        self, message: HistoryItem
    ) -> BaseMessage | None:
        """Convert a history item into a LangChain message object.

        Args:
            message: Dict-based or native LangChain message.

        Returns:
            Normalized message object, or ``None`` for invalid input.
        """
        if isinstance(message, BaseMessage):
            return message
        if not isinstance(message, dict):
            return None

        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str):
            return None

        content = content.strip()
        if not content:
            return None

        if role == "user":
            return HumanMessage(content=content)
        if role == "assistant":
            return AIMessage(content=content)
        if role == "system":
            return SystemMessage(content=content)
        return None

    def _prepare_messages(
        self, user_input: str, history: MessageHistory | None
    ) -> list[BaseMessage]:
        """Prepare trimmed message context ending with current user input.

        Args:
            user_input: Current user prompt.
            history: Optional historical conversation messages.

        Returns:
            Message list ready for agent invocation.
        """
        if not history:
            return [HumanMessage(content=user_input)]

        messages: list[BaseMessage] = []
        for message in history:
            langchain_message = self._message_from_history_item(message)
            if langchain_message is not None:
                messages.append(langchain_message)

        messages = trim_messages(
            messages,
            max_tokens=self.max_history_messages,
            token_counter=len,
            strategy="last",
            include_system=True,
            start_on="human",
        )
        messages.append(HumanMessage(content=user_input))
        return messages

    def _content_to_text(self, content: Any) -> str | None:
        """Extract plain text from model/tool message content.

        Args:
            content: Raw message content which may be text or content blocks.

        Returns:
            Normalized text, or ``None`` when extraction is not possible.
        """
        if isinstance(content, str):
            text = content.strip()
            return text or None

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            merged = "\n".join(
                part.strip() for part in parts if part and part.strip()
            ).strip()
            return merged or None

        return None

    def _extract_answer(self, result: dict[str, Any]) -> str:
        """Extract the most recent assistant text response from agent output.

        Args:
            result: Raw result payload returned by ``agent.invoke``.

        Returns:
            Final assistant answer text, or empty string when unavailable.
        """
        for message in reversed(result.get("messages", [])):
            content = getattr(message, "content", None)
            message_type = getattr(message, "type", None)

            if content is None and isinstance(message, dict):
                if message.get("role") != "assistant":
                    continue
                content = message.get("content")
            elif message_type != "ai":
                continue

            extracted = self._content_to_text(content)
            if extracted:
                return extracted

        return ""

    def _serialize_messages(
        self, messages: MessageHistory
    ) -> list[dict[str, str]]:
        """Serialize normalized messages into role/content dictionaries.

        Args:
            messages: Source message list.

        Returns:
            JSON-serializable list of messages.
        """
        serialized: list[dict[str, str]] = []
        for message in messages:
            langchain_message = (
                message
                if isinstance(message, BaseMessage)
                else self._message_from_history_item(message)
            )
            if langchain_message is None:
                continue

            if isinstance(langchain_message, HumanMessage):
                role = "user"
            elif isinstance(langchain_message, AIMessage):
                role = "assistant"
            elif isinstance(langchain_message, SystemMessage):
                role = "system"
            else:
                continue

            content = self._content_to_text(getattr(langchain_message, "content", None))
            if content is None:
                continue

            serialized.append({"role": role, "content": content})

        return serialized

    def _save_thread(self, messages: MessageHistory) -> None:
        """Persist conversation thread messages to SQLite.

        Args:
            messages: Full thread message list to persist.
        """
        serialized = self._serialize_messages(messages)
        if not serialized:
            return

        payload = json.dumps(serialized, ensure_ascii=True)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                INSERT INTO threads (thread_id, messages_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    messages_json = excluded.messages_json,
                    updated_at = excluded.updated_at
                """,
                (self.thread_id, payload, now, now),
            )
            conn.commit()

    def invoke(
        self, user_input: str, history: MessageHistory | None = None
    ) -> dict[str, Any]:
        """Run the agent for a user query and persist updated thread state.

        Args:
            user_input: User query to process.
            history: Optional prior conversation messages.

        Returns:
            Dictionary containing answer, run metadata and raw agent result.

        Raises:
            ValueError: If ``user_input`` is empty after trimming.
        """
        user_input = user_input.strip()
        if not user_input:
            raise ValueError("user_input must not be empty")

        started_at = perf_counter()
        run_id = str(uuid4())
        messages = self._prepare_messages(user_input, history)

        agent = self.create_agent()
        result = agent.invoke(
            {"messages": messages},
            config={
                "run_name": "base_agent_invoke",
                "tags": ["platon", "base-agent", self.model_name],
                "configurable": {"thread_id": self.thread_id},
                "metadata": {
                    "run_id": run_id,
                    "agent": "base_agent",
                    "model": self.model_name,
                    "thread_id": self.thread_id,
                    "history_messages": len(messages) - 1,
                    "persist_dir": self.persist_dir,
                },
            },
        )

        answer = self._extract_answer(result)
        thread_messages: MessageHistory = []
        if history:
            thread_messages.extend(history)
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
