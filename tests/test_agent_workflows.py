"""Exercise actual graphs and SQLite checkpoints with deterministic fake models."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.agent_orchestrator import AgentOrchestrator
from agent.agents import CodingAgent, DatabaseAgent, ResearchAgent, SupervisorAgent
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedModel:
        return self


def call(name: str, call_id: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "name": name, "args": args, "id": call_id, "type": "tool_call",
    }])


def fake_tool(name: str, calls: list[str]) -> StructuredTool:
    def execute(value: str) -> str:
        calls.append(value)
        return f"result: {value}"
    return StructuredTool.from_function(execute, name=name, description="Local fake tool.")


class WorkflowTests(unittest.TestCase):
    def test_coding_restart_resumes_nested_review_without_repeating_reads(self) -> None:
        reads: list[str] = []
        writes: list[str] = []
        worker_model = ScriptedModel(responses=[
            call("read_file", "read", value="file.py"),
            call("write_file", "write", value="new content"), AIMessage(content="worker done"),
        ])
        supervisor_model = ScriptedModel(responses=[
            call("delegate_coding", "delegate", user_request="zmień plik"),
            AIMessage(content="gotowe"),
        ])
        with TemporaryDirectory() as directory:
            config = AgentOrchestratorConfig(
                working_dir=Path(directory), sqlite_path=Path(directory) / "chat.sqlite3",
            )

            def build() -> AgentOrchestrator:
                worker = CodingAgent(worker_model, Path(directory), tools_list=[
                    fake_tool("read_file", reads), fake_tool("write_file", writes),
                ])
                supervisor = SupervisorAgent(supervisor_model, {"coding": worker})
                return AgentOrchestrator(config=config, agent=supervisor, thread_id="one")

            first = build()
            try:
                payload = first.invoke("zmień plik")
                self.assertEqual(payload["status"], "interrupted")
                self.assertEqual(payload["answer"], "")
                self.assertEqual(reads, ["file.py"])
                self.assertEqual(writes, [])
                reviews = first.pending_interrupts()
                self.assertEqual(len(reviews), 1)
                self.assertEqual(len(first.load_thread_history()), 1)
            finally:
                first.close()

            reopened = build()
            try:
                self.assertEqual(reopened.pending_interrupts(), reviews)
                with self.assertRaisesRegex(ValueError, "pending approval or question"):
                    reopened.invoke("another question")
                with self.assertRaises(ValueError):
                    reopened.resume({"wrong-id": {"decisions": [{"type": "approve"}]}})
                payload = reopened.resume({reviews[0]["id"]: {"decisions": [{"type": "approve"}]}})
                self.assertEqual(payload["status"], "completed")
                self.assertEqual(payload["answer"], "gotowe")
                self.assertEqual(reads, ["file.py"])
                self.assertEqual(writes, ["new content"])
                self.assertEqual(len(reopened.load_thread_history()), 2)
                with self.assertRaises(ValueError):
                    reopened.resume({reviews[0]["id"]: {"decisions": [{"type": "approve"}]}})
                self.assertEqual(writes, ["new content"])
            finally:
                reopened.close()

    def test_database_rejection_never_executes_ingestion(self) -> None:
        writes: list[str] = []
        model = ScriptedModel(responses=[
            call("add_document_to_collection", "write", value="document"),
            AIMessage(content="No document added."),
        ])
        graph = DatabaseAgent(
            model, client_manager=object(),
            tools_list=[fake_tool("add_document_to_collection", writes)],
            checkpointer=InMemorySaver(),
        ).create_agent()
        config = {"configurable": {"thread_id": "reject"}}
        result = graph.invoke({"messages": [HumanMessage(content="Add document")]}, config)
        self.assertTrue(result["__interrupt__"])
        result = graph.invoke(Command(resume={"decisions": [{"type": "reject"}]}), config)
        self.assertEqual(writes, [])
        self.assertEqual(result["messages"][-1].content, "No document added.")

    def test_research_budget_stops_a_model_that_keeps_requesting_tools(self) -> None:
        searches: list[str] = []
        model = ScriptedModel(responses=[
            call("search_web", "first", value="one"),
            call("search_web", "second", value="two"),
            call("search_web", "third", value="three"),
            AIMessage(content="partial evidence"),
        ])
        graph = ResearchAgent(
            model, tools_list=[fake_tool("search_web", searches)], max_tool_calls=2,
        ).create_agent()
        result = graph.invoke({"messages": [HumanMessage(content="search")]})
        self.assertEqual(searches, ["one", "two"])
        self.assertEqual(result["messages"][-1].content, "partial evidence")
        self.assertNotIn("__interrupt__", result)

    def test_http_post_pauses_but_get_does_not(self) -> None:
        calls: list[str] = []
        model = ScriptedModel(responses=[
            call("http_get", "get", value="read"),
            call("http_post", "post", value="send"),
            AIMessage(content="complete"),
        ])
        graph = ResearchAgent(
            model, tools_list=[fake_tool("http_get", calls), fake_tool("http_post", calls)],
            checkpointer=InMemorySaver(),
        ).create_agent()
        config = {"configurable": {"thread_id": "http"}}
        result = graph.invoke({"messages": [HumanMessage(content="Read then send")]}, config)
        self.assertEqual(calls, ["read"])
        self.assertEqual(result["__interrupt__"][0].value["action_requests"][0]["name"], "http_post")
        graph.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
        self.assertEqual(calls, ["read", "send"])


if __name__ == "__main__":
    unittest.main()
