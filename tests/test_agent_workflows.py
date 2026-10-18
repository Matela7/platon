"""Exercise actual graphs and SQLite checkpoints with deterministic fake models."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import Mock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from platon.agent.agent_orchestrator import AgentOrchestrator
from platon.agent.agents import CodingAgent, DatabaseAgent, ResearchAgent, SupervisorAgent
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from platon.agent.models.agent_config import AgentConfig
from platon.agent.tools.file_management import create_document_discovery_tools


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
    def test_document_discovery_accepts_virtual_alias_without_leaving_documents(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            nested = documents / "nested"
            nested.mkdir(parents=True)
            pdf = nested / "example.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            tools = {t.name: t for t in create_document_discovery_tools(documents)}
            self.assertEqual(tools["ls"].invoke({"path": "/documents"}), str(nested))
            self.assertEqual(tools["ls"].invoke({"path": "/documents/nested"}), str(pdf))
            self.assertEqual(tools["glob"].invoke({
                "pattern": "**/*.pdf", "path": "/documents",
            }), str(pdf))
            self.assertIn("outside the documents directory", tools["ls"].invoke({
                "path": "/documents/..",
            }))

    def test_database_exposes_rag_discovery_and_guarded_read_and_searches_after_ingestion(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            documents.mkdir()
            pdf = documents / "example.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            manager = Mock()
            manager.add_document_to_collection.return_value = True
            manager.search.return_value = [{
                "document": "Verified passage", "metadata": {"name": pdf.name, "page": 2},
            }]
            model = ScriptedModel(responses=[
                call("ls", "discover", path="/documents"),
                call("add_document_to_collection", "ingest", collection_name="books",
                     file_path=str(pdf), doc_name=pdf.name),
                call("search_collection", "retrieve", collection_name="books", query="compare"),
                AIMessage(content="Answer based on the retrieved passage."),
            ])
            agent = DatabaseAgent(
                model, manager, config=AgentConfig(backend_root=root),
                checkpointer=InMemorySaver(),
            )
            exposed = []

            def bind_tools(model, tools, **kwargs):
                exposed.append([tool.name for tool in tools])
                return model

            run_config = {"configurable": {"thread_id": "database-rag"}}
            with patch.object(ScriptedModel, "bind_tools", side_effect=bind_tools, autospec=True):
                result = agent.invoke("Analyze example.pdf using books", config=run_config)
                self.assertIn("__interrupt__", result)
                manager.add_document_to_collection.assert_not_called()
                result = agent.invoke(Command(resume={
                    "decisions": [{"type": "approve"}],
                }), config=run_config)
            expected_tools = {
                "ls", "glob", "search_collection", "search_all_collections",
                "get_list_of_collections", "get_collection_info", "add_document_to_collection", "read_file",
            }
            self.assertTrue(exposed)
            for names in exposed:
                self.assertEqual(set(names), expected_tools)
                self.assertEqual(len(names), len(expected_tools))
            manager.add_document_to_collection.assert_called_once_with(
                "books", str(pdf), pdf.name, chunk_size=1000, chunk_overlap=100, reindex=False,
            )
            manager.search.assert_called_once_with(
                "books", "compare", 5, rank=False, rerank=False, candidate_k=None,
                embedding_weight=0.8, semantic_dedup_threshold=None,
            )
            self.assertEqual(result["messages"][-1].content, "Answer based on the retrieved passage.")
            self.assertIn("Verified passage", str(result["messages"]))
            self.assertFalse((root / "shared").exists())

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
