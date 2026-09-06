from __future__ import annotations

import json
import unittest
from typing import Any, cast
from unittest.mock import patch

from aiohttp import web

from backend.agent_chat_ui import (
    _build_ui_html,
    chat,
    conversation,
    conversations,
    history,
    reset_chat,
)


class FakeAgent:
    def __init__(
        self,
        thread_id: str = "thread-a",
        stored: dict[str, list[dict[str, str]]] | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.stored = stored or {thread_id: []}
        self.closed = False

    def invoke(
        self,
        user_input: str,
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "answer": f"received: {user_input}",
            "elapsed_seconds": 0.01,
            "result": {"messages": []},
            "thread_id": self.thread_id,
        }

    def load_thread_history(self) -> list[dict[str, str]]:
        return list(self.stored.get(self.thread_id, []))

    def list_threads(self) -> list[dict[str, str | int]]:
        return [
            {
                "thread_id": thread_id,
                "title": messages[0]["content"] if messages else "New conversation",
                "message_count": len(messages),
                "created_at": "2026-08-22T00:00:00+00:00",
                "updated_at": "2026-08-22T00:00:00+00:00",
            }
            for thread_id, messages in self.stored.items()
        ]

    def thread_exists(self, thread_id: str) -> bool:
        return thread_id in self.stored

    def close(self) -> None:
        self.closed = True


class FakeRequest:
    def __init__(
        self,
        app: dict[str, Any],
        payload: dict[str, Any] | None = None,
        match_info: dict[str, str] | None = None,
    ) -> None:
        self.app = app
        self.payload = payload or {}
        self.match_info = match_info or {}

    async def json(self) -> dict[str, Any]:
        return self.payload


class AgentChatUiTests(unittest.IsolatedAsyncioTestCase):
    def test_ui_lists_selects_and_creates_real_conversations(self) -> None:
        html = _build_ui_html()

        self.assertIn('fetch("/api/conversations")', html)
        self.assertIn("openConversation(conversation.thread_id)", html)
        self.assertIn("thread_id: activeThreadId", html)
        self.assertIn('fetch("/api/history").then(readJson)', html)
        self.assertNotIn("Current conversation", html)
        self.assertNotIn("window.location.reload()", html)

    async def test_history_endpoint_returns_current_ui_history(self) -> None:
        messages = [
            {"role": "user", "content": "Cześć"},
            {"role": "assistant", "content": "Cześć!"},
        ]
        request = cast(Any, type("Request", (), {"app": {"history": messages}})())

        response = await history(cast(web.Request, request))

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.text), messages)

    async def test_conversations_endpoint_returns_all_threads_and_active_id(self) -> None:
        stored = {
            "thread-a": [{"role": "user", "content": "Pierwsza"}],
            "thread-b": [{"role": "user", "content": "Druga"}],
        }
        app: dict[str, Any] = {
            "agent": FakeAgent("thread-a", stored),
            "history": stored["thread-a"],
        }
        request = FakeRequest(app)

        response = await conversations(cast(web.Request, request))
        payload = json.loads(response.text)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["active_thread_id"], "thread-a")
        self.assertEqual(len(payload["conversations"]), 2)

    async def test_conversation_endpoint_switches_without_merging_history(self) -> None:
        stored = {
            "thread-a": [{"role": "user", "content": "Pierwsza"}],
            "thread-b": [{"role": "user", "content": "Druga"}],
        }
        old_agent = FakeAgent("thread-a", stored)
        app: dict[str, Any] = {
            "agent": old_agent,
            "history": list(stored["thread-a"]),
        }
        request = FakeRequest(app, match_info={"thread_id": "thread-b"})

        with patch(
            "backend.agent_chat_ui._build_agent",
            side_effect=lambda thread_id=None: FakeAgent(cast(str, thread_id), stored),
        ):
            response = await conversation(cast(web.Request, request))
        payload = json.loads(response.text)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["thread_id"], "thread-b")
        self.assertEqual(payload["messages"], stored["thread-b"])
        self.assertEqual(app["history"], stored["thread-b"])
        self.assertTrue(old_agent.closed)

    async def test_chat_endpoint_accepts_and_records_a_message(self) -> None:
        app: dict[str, Any] = {"agent": FakeAgent(), "history": []}
        request = FakeRequest(
            app,
            {"message": "test message", "thread_id": "thread-a"},
        )

        response = await chat(cast(web.Request, request))
        payload = json.loads(response.text)

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["answer"], "received: test message")
        self.assertEqual(payload["thread_id"], "thread-a")
        self.assertEqual(
            app["history"],
            [
                {"role": "user", "content": "test message"},
                {"role": "assistant", "content": "received: test message"},
            ],
        )

    async def test_new_chat_creates_a_distinct_empty_thread(self) -> None:
        old_agent = FakeAgent("thread-a")
        app: dict[str, Any] = {
            "agent": old_agent,
            "history": [{"role": "user", "content": "Keep me"}],
        }
        request = FakeRequest(app)

        with patch(
            "backend.agent_chat_ui._build_agent",
            side_effect=lambda thread_id=None: FakeAgent(cast(str, thread_id)),
        ):
            response = await reset_chat(cast(web.Request, request))
        payload = json.loads(response.text)

        self.assertEqual(response.status, 200)
        self.assertNotEqual(payload["thread_id"], "thread-a")
        self.assertEqual(app["history"], [])
        self.assertTrue(old_agent.closed)


if __name__ == "__main__":
    unittest.main()
