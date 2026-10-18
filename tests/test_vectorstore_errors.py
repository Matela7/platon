"""Exercise backend failures through real RAG tools and agent graphs."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from chromadb.errors import NotFoundError, InvalidDimensionException, ChromaAuthError
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from platon.vectorstore.client_manager import ClientManager
from platon.vectorstore.collection_store import CollectionStore
from platon.vectorstore.errors import VectorStoreError
from platon.agent.agents.database_agent import DatabaseAgent
from platon.agent.agents.supervisor_agent import SupervisorAgent
from platon.agent.results import execution_report
from platon.agent.tools.rag import create_rag_tools
from tests.test_agent_workflows import ScriptedModel, call


class VectorStoreErrorTests(unittest.TestCase):
    def manager(self):
        manager = ClientManager()
        manager._client = Mock()
        return manager

    def tool(self, manager, name):
        return next(tool for tool in create_rag_tools(manager) if tool.name == name)

    def test_open_failure_preserves_cause_and_can_be_retried(self):
        manager = ClientManager()
        failure = PermissionError("database directory denied")
        with patch("platon.vectorstore.chroma_utils.start_chromadb", side_effect=failure):
            with self.assertRaises(VectorStoreError) as caught:
                _ = manager.client
        self.assertIs(caught.exception.__cause__, failure)
        self.assertIsNone(manager._client)
        with patch("platon.vectorstore.chroma_utils.start_chromadb", return_value=Mock()) as start:
            _ = manager.client
            _ = manager.client
            start.assert_called_once()

    def test_chroma_errors_reach_tool_with_correct_categories(self):
        for failure, category in [(NotFoundError("missing"), "lookup"),
                                  (InvalidDimensionException("dimension mismatch"), "validation"),
                                  (ChromaAuthError("denied"), "permission"),
                                  (TimeoutError("offline"), "transient")]:
            with self.subTest(category=category):
                manager = self.manager()
                manager._client.get_collection.side_effect = failure
                tool = self.tool(manager, "search_collection")
                message = tool.invoke({"name": tool.name, "args": {
                    "collection_name": "private", "query": "question"},
                    "id": "search", "type": "tool_call"})
                self.assertEqual(message.status, "error")
                details = json.loads(message.content)["errors"][0]
                self.assertEqual(details["category"], category)
                self.assertEqual(details["retryable"], category == "transient")
                self.assertIn("private", details["message"])
                manager._client.get_or_create_collection.assert_not_called()

    def test_listing_failure_is_not_empty_success(self):
        manager = self.manager()
        manager._client.list_collections.side_effect = OSError("corrupt database")
        result = json.loads(self.tool(manager, "get_list_of_collections").invoke({}))
        self.assertEqual(result["status"], "error")
        self.assertIn("listing collections", result["errors"][0]["message"])

    def test_embedding_failure_reaches_tool(self):
        manager = self.manager()
        with patch("platon.vectorstore.chroma_utils.get_model", side_effect=RuntimeError("embedding unavailable")):
            result = json.loads(self.tool(manager, "search_collection").invoke({
                "collection_name": "private", "query": "question"}))
        self.assertEqual(result["status"], "error")
        self.assertIn("embedding unavailable", result["errors"][0]["message"])

    def test_empty_search_remains_success(self):
        manager = self.manager()
        with patch("platon.vectorstore.collection_store.similarity_search", return_value={"documents": [[]]}):
            self.assertEqual(self.tool(manager, "search_collection").invoke({
                "collection_name": "private", "query": "question"}), [])

    def test_empty_pdf_is_not_reported_as_ingested(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scan.pdf"
            path.touch()
            manager = self.manager()
            with patch("platon.vectorstore.collection_store.load_pdf_pages_document", return_value=[]):
                result = json.loads(self.tool(manager, "add_document_to_collection").invoke({
                    "collection_name": "private", "file_path": str(path), "doc_name": "scan"}))
            self.assertEqual(result["status"], "error")
            self.assertIn("no extractable text", result["errors"][0]["message"])
            manager._client.get_or_create_collection.assert_not_called()

    def test_missing_and_invalid_documents_preserve_original_causes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "file.unknown"
            for exists, expected in [(False, FileNotFoundError), (True, ValueError)]:
                if exists:
                    path.touch()
                with self.assertRaises(VectorStoreError) as caught:
                    CollectionStore(Mock(), "private").add_document(str(path), "file")
                self.assertIsInstance(caught.exception.__cause__, expected)

    def test_database_error_reaches_supervisor_report(self):
        manager = self.manager()
        manager._client.get_collection.side_effect = NotFoundError("missing collection")
        database = DatabaseAgent(ScriptedModel(responses=[
            call("search_collection", "search", collection_name="private", query="question"),
            AIMessage(content="Could not search the database."),
        ]), manager)
        supervisor = SupervisorAgent(ScriptedModel(responses=[
            call("delegate_database", "delegate", user_request="question"),
            AIMessage(content="Database unavailable."),
        ]), {"database": database})
        result = supervisor.invoke("question")
        report = execution_report(result["messages"])
        self.assertNotEqual(report["status"], "completed")
        self.assertEqual(report["errors"][0]["category"], "lookup")
        delegation = next(message for message in result["messages"] if isinstance(message, ToolMessage))
        self.assertEqual(delegation.artifact["evidence"][0]["status"], "error")
        self.assertIn("missing collection", str(delegation.artifact["errors"]))

    def test_ingestion_timeout_after_approval_is_not_retryable(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "document.txt"
            path.write_text("some content", encoding="utf-8")
            manager = self.manager()
            database = DatabaseAgent(ScriptedModel(responses=[
                call("add_document_to_collection", "write", collection_name="private",
                     file_path=str(path), doc_name="document"),
                AIMessage(content="Write outcome is uncertain."),
            ]), manager, checkpointer=InMemorySaver())
            config = {"configurable": {"thread_id": "write-error"}}
            pending = database.invoke("add document", config=config)
            self.assertTrue(pending["__interrupt__"])
            with patch("platon.vectorstore.collection_store.add_document_to_vector_store",
                       side_effect=TimeoutError("write timed out")):
                result = database.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config)
            message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
            self.assertEqual(message.status, "error")
            report = execution_report(result["messages"])
            self.assertNotEqual(report["status"], "completed")
            self.assertFalse(report["errors"][0]["retryable"])
            self.assertIn("write timed out", report["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
