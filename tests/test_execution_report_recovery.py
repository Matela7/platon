"""Recovered RAG lookups remain visible without failing the final report."""

import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from platon.agent.results import execution_report


class ExecutionReportRecoveryTests(unittest.TestCase):
    def test_lookup_resolved_after_ingestion(self):
        messages = [
            HumanMessage(content="Analyze my document"),
            AIMessage(content="", tool_calls=[{"id": "search1", "name": "search_collection",
                                                "args": {"collection_name": "book", "query": "topic"}}]),
            ToolMessage(content='{"status":"error","errors":[{"category":"lookup","message":"Collection missing"}]}',
                        name="search_collection", tool_call_id="search1"),
            AIMessage(content="", tool_calls=[{"id": "search2", "name": "search_collection",
                                                "args": {"collection_name": "book", "query": "topic"}}]),
            ToolMessage(content='[{"document":"confirmed excerpt"}]',
                        name="search_collection", tool_call_id="search2"),
            AIMessage(content="Analysis backed by the excerpt"),
        ]
        report = execution_report(messages)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["evidence"][0]["status"], "error")
        self.assertEqual(report["evidence"][1]["status"], "success")

    def test_lookup_in_different_collection_does_not_resolve_error(self):
        messages = [
            HumanMessage(content="Analyze two documents"),
            AIMessage(content="", tool_calls=[{"id": "search1", "name": "search_collection",
                                                "args": {"collection_name": "missing", "query": "topic"}}]),
            ToolMessage(content='{"status":"error","errors":[{"category":"lookup","message":"Collection missing"}]}',
                        name="search_collection", tool_call_id="search1"),
            AIMessage(content="", tool_calls=[{"id": "search2", "name": "search_collection",
                                                "args": {"collection_name": "another", "query": "topic"}}]),
            ToolMessage(content='[{"document":"another excerpt"}]',
                        name="search_collection", tool_call_id="search2"),
            AIMessage(content="Partial analysis"),
        ]
        report = execution_report(messages)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["errors"][0]["category"], "lookup")

    def test_second_encoded_failure_does_not_resolve_lookup(self):
        messages = [
            HumanMessage(content="Analyze document"),
            AIMessage(content="", tool_calls=[{"id": "search1", "name": "search_collection",
                                                "args": {"collection_name": "missing", "query": "one"}}]),
            ToolMessage(content='{"status":"error","errors":[{"category":"lookup","message":"Missing"}]}',
                        name="search_collection", tool_call_id="search1"),
            AIMessage(content="", tool_calls=[{"id": "search2", "name": "search_collection",
                                                "args": {"collection_name": "missing", "query": "two"}}]),
            ToolMessage(content='{"status":"error","errors":[{"category":"lookup","message":"Still missing"}]}',
                        name="search_collection", tool_call_id="search2"),
            AIMessage(content="Could not analyze"),
        ]
        report = execution_report(messages)
        self.assertEqual(report["status"], "partial")
        self.assertEqual([item["message"] for item in report["errors"]], ["Missing", "Still missing"])


if __name__ == "__main__":
    unittest.main()
