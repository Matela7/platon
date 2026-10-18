"""Regression tests for bounded delegation and meaningful retries."""

import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime

from platon.agent.adapters.delegation import AgentToolAdapter
from platon.agent.context import bounded_messages
from tests.test_agent_reliability import RecordingWorker


def runtime(messages):
    return ToolRuntime(state={"messages": messages}, context=None, config={},
                       stream_writer=lambda _: None, tool_call_id="new", store=None)


def previous(request, task, status="error"):
    report = {"status": status, "answer": "", "evidence": [], "errors": [
        {"category": "execution", "retryable": False, "message": "context length exceeded"}],
        "user_request": request, "task": task}
    return ToolMessage(content=json.dumps(report), artifact=report, name="delegate_database",
                       tool_call_id="previous")


class DelegationBudgetTests(unittest.TestCase):
    def test_paraphrased_user_request_warns_and_runs_database_agent(self):
        worker = RecordingWorker()
        latest = "Wyszukaj informacje o Izabeli Łęckiej i Szlangbaumie w Lalce"
        copied = "Wyszukaj informacje na temat Izabeli Łęckiej i jej podejścia to Szlangbauma w Lalce"
        adapter = AgentToolAdapter("database", worker, "Database")
        with patch("platon.agent.adapters.delegation.LOGGER.warning") as warning:
            _, report = adapter.invoke(
                copied,
                "Search lalka.pdf for Izabela Łęcka and Szlangbaum passages",
                runtime=runtime([HumanMessage(content=latest)]),
            )
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(worker.received), 1)
        warning.assert_called_once()

    def test_large_tool_result_is_bounded_without_orphaning_its_call(self):
        messages = [HumanMessage(content="Analyze documents"),
                    AIMessage(content="", tool_calls=[{"name": "search", "args": {"query": "x"}, "id": "search-1"}]),
                    ToolMessage(content="passage " * 12_000, name="search", tool_call_id="search-1")]
        result = bounded_messages(messages, 2)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1].tool_calls[0]["id"], result[2].tool_call_id)
        self.assertLess(sum(len(str(m.content)) for m in result), 20_000)
        self.assertEqual(len(messages[2].content), len("passage " * 12_000))

    def test_dependency_report_samples_both_ends_and_keeps_errors(self):
        worker = RecordingWorker()
        findings = [{"tool": "search", "status": "success", "output": [
            {"document": f"book {book} passage {i} " + "x" * 500,
             "metadata": {"page": i, "source": book}} for i in range(25)]}
            for book in ("A", "B")]
        report = {"status": "partial", "answer": "Found both books", "evidence": findings,
                  "errors": [{"category": "execution", "message": "One quote unresolved", "retryable": False}]}
        source = ToolMessage(content="x" * 100_000, artifact=report, name="delegate_database", tool_call_id="old")
        _, result = AgentToolAdapter("coding", worker, "Code").invoke(
            "Make report", runtime=runtime([HumanMessage(content="Make report"), source]))
        self.assertEqual(result["status"], "completed")
        assignment = json.loads(worker.received[0][0])
        dependency = assignment["dependency_evidence"][0]["report"]
        self.assertIn("book A", str(dependency))
        self.assertIn("book B", str(dependency))
        self.assertIn("One quote unresolved", str(dependency))
        self.assertEqual(dependency["evidence"][0]["omitted_passages"], 21)
        self.assertEqual(dependency["evidence"][1]["omitted_passages"], 21)
        self.assertLess(len(worker.received[0][0]), 10_000)

    def test_paraphrased_retry_needs_changed_approach_and_has_one_attempt(self):
        worker = RecordingWorker()
        request = "Analyze Lalka"
        old = previous(request, "Analyze Lalka and give citations")
        adapter = AgentToolAdapter("database", worker, "Database")
        messages = [HumanMessage(content=request), old]
        _, blocked = adapter.invoke(request, "Analyze Lalka, give citations", runtime=runtime(messages))
        self.assertEqual(blocked["status"], "error")
        self.assertEqual(worker.received, [])
        _, retried = adapter.invoke(request, "Analyze Lalka, give citations",
                                    retry_reason="Use fewer passages per search and cite the strongest results",
                                    runtime=runtime(messages))
        self.assertEqual(retried["status"], "completed")
        _, second = adapter.invoke(request, "Analyze Lalka, give citations",
                                   retry_reason="Use a different query and read another page",
                                   runtime=runtime(messages + [previous(request, "Analyze Lalka, give citations")]))
        self.assertEqual(second["status"], "error")
        self.assertEqual(len(worker.received), 1)

    def test_non_retryable_validation_failure_is_not_replayed(self):
        worker = RecordingWorker()
        old = previous("Analyze Lalka", "Analyze Lalka", status="error")
        old.artifact["errors"][0]["category"] = "validation"
        _, report = AgentToolAdapter("database", worker, "Database").invoke(
            "Analyze Lalka", "Analyze Lalka", "I will use a different query to find the text",
            runtime=runtime([HumanMessage(content="Analyze Lalka"), old]))
        self.assertEqual(report["status"], "error")
        self.assertEqual(worker.received, [])

    def test_distinct_documents_are_not_treated_as_a_retry(self):
        worker = RecordingWorker()
        request = "Compare the supplied documents"
        old = previous(request, "Analyze the perspective in /documents/lalka.pdf", status="completed")
        _, report = AgentToolAdapter("database", worker, "Database").invoke(
            request, "Analyze the perspective in /documents/ciekawaksiazka.pdf",
            runtime=runtime([HumanMessage(content=request), old]))
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(worker.received), 1)

    def test_completed_result_is_reused_when_supervisor_expands_the_task(self):
        worker = RecordingWorker()
        request = "Wyszukaj informacje o Izabeli Łęckiej i Szlangbaumie w Lalce"
        first_task = "Znajdź informacje, cytaty i analizy o relacji Izabeli Łęckiej ze Szlangbaumem."
        old = previous(request, first_task, status="completed")
        old.artifact["answer"] = "Znalezione cytaty"

        _, report = AgentToolAdapter("database", worker, "Database").invoke(
            request,
            "Przeszukaj dokumenty dokładniej i podaj wszystkie cytaty oraz numery stron.",
            runtime=runtime([HumanMessage(content=request), old]),
        )

        self.assertIs(report, old.artifact)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(worker.received, [])

    def test_summary_human_message_does_not_reject_original_request(self):
        worker = RecordingWorker()
        summary = HumanMessage(content="Previous user asked to analyze two books.",
                               additional_kwargs={"lc_source": "summarization"})
        _, report = AgentToolAdapter("database", worker, "Database").invoke(
            "Analyze Lalka", runtime=runtime([summary]))
        self.assertEqual(report["status"], "completed")


if __name__ == "__main__":
    unittest.main()
