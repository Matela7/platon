import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain_ollama import ChatOllama
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, trim_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool
from agent.tools import create_search_tools, create_utils_tools
from agent.prompt_loader import load_prompt
from vectorstore.client_manager import ClientManager


class BaseAgent:
    def __init__(
        self,
        model_name: str = "deepseek-r1:8b",
        model: ChatOllama | None = None,
        working_dir: Path = Path("./"),
        persist_dir: str | None = "./chroma_data",
        tools_list: list[tool] = None,
        cm: ClientManager = None,
        memory: InMemorySaver | None = None,
        thread_id: str | None = None,
        sqlite_path: str | Path | None = None,
        prompt: str | None = None,
        max_history_messages: int = 24,
    ):
        self.model_name = model_name
        self.model = model
        self.persist_dir = persist_dir
        self.tools_list = tools_list
        self.memory = memory or InMemorySaver()
        self.thread_id = thread_id or str(uuid4())
        self.prompt = prompt
        self.working_dir = working_dir
        self.cm = cm
        self.max_history_messages = max_history_messages
        self.sqlite_path = Path(sqlite_path) if sqlite_path is not None else self.working_dir / "agent_threads.sqlite3"

        self._setup_model()
        self._init_sqlite()
        if self.tools_list is None:
            self.tools_list = self._setup_tools()

    def _setup_model(self):
        self.model = ChatOllama(model=self.model_name)

    def _setup_tools(self) -> list:
        if self.cm is None:
            self.cm = ClientManager(persist_dir=self.persist_dir)
        search_tools = create_search_tools(self.cm)
        utils_tools = create_utils_tools()
        return list(search_tools) + list(utils_tools)

    def _default_prompt(self) -> str:
        return load_prompt("agent_prompt.md")

    def _init_sqlite(self) -> None:
        if self.sqlite_path is None:
            return
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

    def _content_to_text(self, content: Any) -> str | None:
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
            merged = "\n".join(part.strip() for part in parts if part and part.strip()).strip()
            return merged or None

        return None

    def _serialize_messages(self, messages: list[dict[str, str] | BaseMessage]) -> list[dict[str, str]]:
        serialized: list[dict[str, str]] = []
        for message in messages:
            langchain_message = (
                message if isinstance(message, BaseMessage) else self._message_from_history_item(message)
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

    def _save_thread(self, messages: list[dict[str, str] | BaseMessage]) -> None:
        if self.sqlite_path is None:
            return

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

    def create_agent(self, prompt: str | None = None) -> object:
        if self.model is None:
            self._setup_model()

        system_prompt = prompt or self.prompt or self._default_prompt()
        self.prompt = system_prompt

        return create_agent(
            model=self.model,
            tools=self.tools_list,
            system_prompt=system_prompt,
            checkpointer=self.memory,
        )

    def _message_from_history_item(self, message: dict[str, str] | BaseMessage) -> BaseMessage | None:
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

    def _prepare_messages(self, user_input: str, history: list[dict[str, str] | BaseMessage] | None) -> list[BaseMessage]:
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

    def _extract_answer(self, result: dict[str, Any]) -> str:
        for message in reversed(result.get("messages", [])):
            content = getattr(message, "content", None)
            message_type = getattr(message, "type", None)

            if content is None and isinstance(message, dict):
                if message.get("role") != "assistant":
                    continue
                content = message.get("content")
            elif message_type != "ai":
                continue

            if isinstance(content, str) and content.strip():
                return content.strip()

            if isinstance(content, list):
                parts = [
                    item.get("text", "") if isinstance(item, dict) else item
                    for item in content
                    if isinstance(item, (str, dict))
                ]
                answer = "\n".join(part.strip() for part in parts if part and part.strip())
                if answer:
                    return answer

        return ""

    def invoke(self, user_input: str, history: list[dict[str, str] | BaseMessage] | None = None) -> dict:
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
                "configurable": {"thread_id": self.thread_id},
                "metadata": {
                    "run_id": run_id,
                    "model": self.model_name,
                    "history_messages": len(messages) - 1,
                },
            },
        )

        answer = self._extract_answer(result)
        thread_messages: list[dict[str, str] | BaseMessage] = []
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