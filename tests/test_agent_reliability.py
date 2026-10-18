"""Regression scenarios for dependency evidence, failures and host tool isolation."""

import json
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime

from platon.agent.adapters.delegation import AgentToolAdapter
from platon.agent.agents.supervisor_agent import SupervisorAgent
from platon.agent.base_agent import BaseAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.context import bounded_messages
from platon.agent.results import execution_report
from platon.agent.cancellation import RunStopped, StopHandler
from platon.agent.tools.execution import create_execution_tools
from platon.agent.tools.file_management import create_file_management_tools
from platon.agent.tools.rag import create_rag_tools
from tests.test_agent_workflows import ScriptedModel, call
from platon.vectorstore.client_manager import ClientManager
from platon.vectorstore.collection_store import CollectionStore
from platon.vectorstore.errors import VectorStoreError


class RecordingWorker(BaseAgent):
    def __init__(self):
        super().__init__(object(), prompt="test")
        self.received = []

    def invoke(self, task, *, context_messages=None, config=None):
        self.received.append((task, context_messages))
        return {"messages": [HumanMessage(content=task), AIMessage(content="report saved with sources")]}


class ReliabilityTests(unittest.TestCase):
    def test_stop_terminates_python_process_before_later_side_effect(self):
        stop = Event()
        with TemporaryDirectory() as directory:
            tool = next(t for t in create_execution_tools(Path(directory)) if t.name == "run_python")
            code = "from pathlib import Path\nimport time\nPath('started').write_text('yes')\ntime.sleep(20)\nPath('finished').write_text('yes')"
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(tool.invoke, {"code":code}, {"callbacks":[StopHandler(stop)]})
                try:
                    deadline = monotonic() + 3
                    while not Path(directory,"started").exists() and monotonic() < deadline:
                        stop.wait(.01)
                    self.assertTrue(Path(directory,"started").exists())
                finally:
                    stop.set()
                with self.assertRaises(RunStopped):
                    future.result(timeout=3)
            self.assertFalse(Path(directory,"finished").exists())

    def test_successful_retry_does_not_hide_a_real_execution_error(self):
        messages = [HumanMessage(content="read files"),
            call("read_file", "one", file_path="missing.txt"),
            ToolMessage(content="file not found", tool_call_id="one", name="read_file", status="error"),
            call("read_file", "two", file_path="present.txt"),
            ToolMessage(content="confirmed result", tool_call_id="two", name="read_file"),
            AIMessage(content="one file read")]
        self.assertEqual(execution_report(messages)["status"], "partial")

    def test_dependency_sources_reach_next_agent_and_completed_task_is_reused(self):
        research = BaseAgent(ScriptedModel(responses=[AIMessage(content="Confirmed result from https://example.com/source, checked today.")]), prompt="test")
        coding = RecordingWorker()
        request = "Find data and save a report"
        model = ScriptedModel(responses=[
            call("delegate_research", "research", user_request=request, task="Find data"),
            call("delegate_coding", "coding", user_request=request, task="Save report with supplied findings"),
            call("delegate_coding", "repeat", user_request=request, task="Save report with supplied findings"),
            AIMessage(content="done"),
        ])
        result = SupervisorAgent(model, {"research":research,"coding":coding}).invoke(request)
        self.assertEqual(len(coding.received), 1)
        self.assertIn("https://example.com/source", coding.received[0][0])
        self.assertIn("Find data", coding.received[0][0])
        self.assertEqual(execution_report(result["messages"])["status"], "completed")

    def test_dependencies_and_original_constraints_survive_context_trimming(self):
        seen = []
        original = ScriptedModel._generate
        def record(model, messages, *args, **kwargs):
            seen.append(messages)
            return original(model, messages, *args, **kwargs)
        def read(value: str):
            return "read completed"
        worker = BaseAgent(
            ScriptedModel(responses=[call("read", "one", value="one"), call("read", "two", value="two"), AIMessage(content="done")]),
            config=AgentConfig(max_history_messages=2), prompt="test",
            tools_list=[StructuredTool.from_function(read, description="Read evidence.")],
        )
        runtime = ToolRuntime(state={"messages":[
            HumanMessage(content="Create a report; keep it private"),
            call("delegate_research", "research", user_request="Create a report"),
            ToolMessage(content="source", tool_call_id="research", name="delegate_research",
                        artifact={"status":"completed","answer":"https://example.com/source"}),
        ]}, context=None, config={}, stream_writer=lambda _: None, tool_call_id="coding", store=None)
        with patch.object(ScriptedModel, "_generate", record):
            _, report = AgentToolAdapter("coding", worker, "Code").invoke("Create a report", runtime=runtime)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(len(seen), 3)
        for messages in seen:
            self.assertIn("keep it private", str(messages))
            self.assertIn("https://example.com/source", str(messages))

    def test_failed_specialist_preserves_confirmed_tool_evidence(self):
        def read(value: str):
            return "confirmed source https://example.com/evidence"
        model = ScriptedModel(responses=[call("read", "read", value="query"), AIMessage(content="unused")])
        worker = BaseAgent(model, tools_list=[StructuredTool.from_function(read, description="Read evidence.")], prompt="test")
        original = ScriptedModel._generate
        def fail(model, messages, *args, **kwargs):
            if isinstance(messages[-1], ToolMessage):
                raise TimeoutError("model failed after read")
            return original(model, messages, *args, **kwargs)
        with patch.object(ScriptedModel, "_generate", fail):
            _, report = AgentToolAdapter("research",worker,"Research").invoke("query")
        self.assertEqual(report["status"], "partial")
        self.assertIn("https://example.com/evidence", str(report["evidence"]))
        self.assertIn("model failed", report["errors"][0]["message"])

    def test_context_does_not_split_current_tool_call_pairs(self):
        messages = [HumanMessage(content="old"),AIMessage(content="old answer"),HumanMessage(content="new"),
                    call("read", "read", value="file"),ToolMessage(content="result",tool_call_id="read")]
        trimmed = bounded_messages(messages, 2)
        self.assertEqual(trimmed, messages[2:])

    def test_missing_file_is_error_but_error_text_in_a_real_file_is_success(self):
        with TemporaryDirectory() as directory:
            Path(directory,"real.txt").write_text("Error: this is legitimate file content")
            read = next(t for t in create_file_management_tools(Path(directory)) if t.name == "read_file")
            for path, status in [("missing.txt","error"),("../escape.txt","error"),("real.txt","success")]:
                message = read.invoke({"name":"read_file","args":{"file_path":path},"id":path,"type":"tool_call"})
                self.assertEqual(message.status, status)
            self.assertIn("validation", read.invoke({"file_path":"missing.txt"}))

    def test_host_process_cwd_is_unchanged_and_failure_preserves_output(self):
        original = Path.cwd()
        with TemporaryDirectory() as directory:
            tools = {t.name:t for t in create_execution_tools(Path(directory))}
            output = tools["run_python"].invoke({"code":"print('ok')"})
            self.assertEqual(output.strip(), "ok")
            self.assertEqual(Path.cwd(), original)
            failure = tools["run_python"].invoke({"name":"run_python","args":{"code":"print('finished first step'); raise RuntimeError('boom')"},"id":"python","type":"tool_call"})
            self.assertEqual(failure.status, "error")
            self.assertIn("finished first step", failure.content)
            self.assertIn("boom", failure.content)
            shell = tools["run_shell"].invoke({"command":"echo shell-ok"})
            self.assertIn("shell-ok", shell)
            with patch("platon.agent.tools.execution.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 1, output=b"first step completed")):
                timeout = json.loads(tools["run_python"].invoke({"code":"long task"}))
            self.assertIn("first step completed", str(timeout["errors"][0]["partial_results"]))
            self.assertFalse(timeout["errors"][0]["retryable"])

    def test_retrieval_does_not_create_missing_collection(self):
        client = Mock()
        client.get_collection.side_effect = LookupError("missing collection")
        with self.assertRaises(VectorStoreError) as raised:
            CollectionStore(client,"missing").search("query")
        self.assertIsInstance(raised.exception.__cause__, LookupError)
        client.get_or_create_collection.assert_not_called()

    def test_collection_failure_preserves_previous_collection_results(self):
        manager = ClientManager()
        manager._client = Mock()
        manager._client.list_collections.return_value = [Mock(name="first"),Mock(name="second")]
        manager._client.list_collections.return_value[0].name = "first"
        manager._client.list_collections.return_value[1].name = "second"
        first = Mock()
        first.search.return_value = [{"document":"confirmed passage","similarity":1,"metadata":{"name":"document","page":2}}]
        second = Mock()
        second.search.side_effect = TimeoutError("unavailable")
        tool = next(t for t in create_rag_tools(manager) if t.name == "search_all_collections")
        with patch.object(manager,"get_collection",side_effect=[first,second]):
            report = json.loads(tool.invoke({"query":"query"}))
        self.assertEqual(report["status"], "error")
        self.assertIn("confirmed passage", str(report))
        self.assertEqual(report["errors"][0]["remaining_collections"], ["second"])
        self.assertEqual(report["errors"][0]["category"], "transient")
        self.assertTrue(report["errors"][0]["retryable"])


if __name__ == "__main__":
    unittest.main()
