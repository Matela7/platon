"""Run actual checkpointed graphs to verify conversation and recovery behavior."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from agent.agent_orchestrator import AgentOrchestrator
from agent.base_agent import BaseAgent
from agent.agents.supervisor_agent import SupervisorAgent
from agent.models.agent_config import AgentConfig
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from agent.results import final_answer
from agent.cancellation import current_stop_event
from tests.test_agent_workflows import ScriptedModel, call


class AgentOrchestratorTests(unittest.TestCase):
    def test_invalid_delegation_is_corrected_without_exposing_schema_as_final_error(self):
        worker = BaseAgent(ScriptedModel(responses=[AIMessage(content="Ustalenia ze źródłem")]), prompt="test")
        supervisor = SupervisorAgent(ScriptedModel(responses=[
            call("delegate_research", "invalid", query="Krwawy Piątek", language="pl", locale="pl-PL"),
            call("delegate_research", "corrected", user_request="wyszukaj Krwawy Piątek", task="Sprawdź źródła i odpowiedz po polsku"),
            AIMessage(content="Wynik po polsku"),
        ]), {"research":worker}, prompt="test")
        with TemporaryDirectory() as directory:
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"), agent=supervisor)
            try:
                result = orchestrator.invoke("wyszukaj Krwawy Piątek")
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["answer"], "Wynik po polsku")
                messages = orchestrator._snapshot().values["messages"]
                self.assertIn("Correct your tool arguments", next(m.content for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == "invalid"))
                self.assertEqual(orchestrator.pending_interrupts(), [])
            finally:
                orchestrator.close()

    def test_stop_during_generation_cleans_checkpoint_and_allows_next_turn(self):
        entered, release = Event(), Event()
        def tokens(model, messages, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content="Początek odpowiedzi"))
            entered.set()
            release.wait(3)
            yield ChatGenerationChunk(message=AIMessageChunk(content=" — koniec"))
        with TemporaryDirectory() as directory:
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"),
                agent=BaseAgent(ScriptedModel(responses=[AIMessage(content="Nowa odpowiedź")]), prompt="test"))
            try:
                with patch.object(ScriptedModel, "_stream", tokens), ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(orchestrator.invoke, "pierwsze zadanie")
                    try:
                        self.assertTrue(entered.wait(3))
                        self.assertTrue(orchestrator.stop())
                    finally:
                        release.set()
                    result = future.result(timeout=3)
                self.assertEqual(result["status"], "stopped")
                self.assertFalse(result["can_retry"])
                self.assertFalse(orchestrator._running.is_set())
                self.assertFalse(orchestrator.stop())
                self.assertEqual(orchestrator.invoke("następne zadanie")["answer"], "Nowa odpowiedź")
                self.assertEqual([m["content"] for m in orchestrator.load_thread_history() if m["role"] == "user"],
                                 ["pierwsze zadanie", "następne zadanie"])
            finally:
                orchestrator.close()

    def test_preset_stop_event_preserves_user_input(self):
        stop = Event()
        stop.set()
        with TemporaryDirectory() as directory:
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"),
                agent=BaseAgent(ScriptedModel(responses=[AIMessage(content="dalej")]), prompt="test"))
            try:
                result = orchestrator._result(orchestrator.stream("zatrzymaj przed generacją", stop_event=stop))
                self.assertEqual(result["status"], "stopped")
                self.assertEqual(orchestrator.load_thread_history()[0]["content"], "zatrzymaj przed generacją")
                self.assertEqual(orchestrator.invoke("kolejna wiadomość")["answer"], "dalej")
            finally:
                orchestrator.close()

    def test_stop_reaches_delegated_tool_and_prevents_following_work(self):
        stop = Event()
        calls = []
        def read(value: str):
            self.assertIs(current_stop_event(), stop)
            calls.append(value)
            stop.set()
            return "confirmed read"
        tool = StructuredTool.from_function(read, description="Read evidence.")
        worker = BaseAgent(ScriptedModel(responses=[call("read", "read", value="first"),
            call("read", "unwanted", value="second"), AIMessage(content="worker done")]), prompt="test", tools_list=[tool])
        supervisor = SupervisorAgent(ScriptedModel(responses=[call("delegate_research", "delegate", user_request="szukaj"),
            AIMessage(content="następny wynik")]), {"research":worker}, prompt="test")
        with TemporaryDirectory() as directory:
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"), agent=supervisor)
            try:
                result = orchestrator._result(orchestrator.stream("szukaj", stop_event=stop))
                self.assertEqual(result["status"], "stopped")
                self.assertEqual(calls, ["first"])
                self.assertEqual(orchestrator.pending_interrupts(), [])
                self.assertFalse(orchestrator.can_retry())
                self.assertEqual(orchestrator.invoke("nowe pytanie")["answer"], "następny wynik")
            finally:
                orchestrator.close()

    def test_discard_clarification_allows_a_new_task(self):
        supervisor = SupervisorAgent(ScriptedModel(responses=[call("ask_user", "ask", question="Który plik?"),
            AIMessage(content="nowe zadanie")]), {}, prompt="test")
        with TemporaryDirectory() as directory:
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"), agent=supervisor)
            try:
                self.assertEqual(orchestrator.invoke("zmień plik")["status"], "interrupted")
                self.assertTrue(orchestrator.discard_pending_run())
                self.assertFalse(orchestrator.can_retry())
                self.assertEqual(orchestrator.pending_interrupts(), [])
                self.assertEqual(orchestrator.invoke("inna prośba")["answer"], "nowe zadanie")
                self.assertFalse(orchestrator.discard_pending_run())
            finally:
                orchestrator.close()

    def test_lists_saved_threads_and_bootstraps_legacy_history(self):
        with TemporaryDirectory() as directory:
            config = AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3")
            first = AgentOrchestrator(config=config, agent=BaseAgent(ScriptedModel(responses=[AIMessage(content="done")]), prompt="test"), thread_id="one")
            with self.assertNoLogs("platon", level="ERROR"):
                first.invoke("First subject")
            first.close()
            second = AgentOrchestrator(config=config, agent=BaseAgent(ScriptedModel(responses=[AIMessage(content="done")]), prompt="test"), thread_id="two")
            try:
                second.store.save("two", [{"role":"user", "content":"Second subject"}, {"role":"assistant", "content":"Earlier answer"}])
                second.invoke("new question")
                messages = second._snapshot().values["messages"]
                self.assertEqual([m.content for m in messages], ["Second subject", "Earlier answer", "new question", "done"])
                self.assertEqual([t["thread_id"] for t in second.list_threads()], ["two", "one"])
            finally:
                second.close()
            reopened = AgentOrchestrator(config=config, agent=BaseAgent(ScriptedModel(responses=[AIMessage(content="again")]), prompt="test"))
            try:
                self.assertEqual(reopened.thread_id, "two")
                reopened.invoke("follow-up")
                messages = reopened._snapshot().values["messages"]
                self.assertEqual(sum(isinstance(m, HumanMessage) for m in messages), 3)
            finally:
                reopened.close()

    def test_clarification_uses_injected_checkpointer(self):
        with TemporaryDirectory() as directory:
            agent = SupervisorAgent(ScriptedModel(responses=[call("ask_user", "ask", question="Which file?"), AIMessage(content="done")]), {}, prompt="test", checkpointer=InMemorySaver())
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"), agent=agent)
            try:
                result = orchestrator.invoke("edit file")
                pending = orchestrator.pending_interrupts()
                self.assertEqual(len(pending), 1)
                self.assertEqual(result["status"], "interrupted")
                with self.assertRaises(ValueError):
                    orchestrator.resume({pending[0]["id"]:{"answer":""}})
                result = orchestrator.resume({pending[0]["id"]:{"answer":"example.py"}})
                self.assertEqual(result["answer"], "done")
                self.assertEqual(len(orchestrator.load_thread_history()), 2)
            finally:
                orchestrator.close()

    def test_error_keeps_tool_progress_and_retry_does_not_repeat_tool(self):
        calls = []
        def read(value: str):
            calls.append(value)
            return "confirmed evidence"
        model = ScriptedModel(responses=[call("read", "read", value="file"), AIMessage(content="done")])
        with TemporaryDirectory() as directory:
            agent = BaseAgent(model, prompt="test", tools_list=[StructuredTool.from_function(read, description="Read evidence.")])
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"),agent=agent)
            original = ScriptedModel._generate
            def fail_after_tool(model, messages, *args, **kwargs):
                if isinstance(messages[-1], ToolMessage):
                    raise TimeoutError("model unavailable after tool")
                return original(model, messages, *args, **kwargs)
            try:
                with patch.object(ScriptedModel, "_generate", fail_after_tool):
                    result = orchestrator.invoke("read")
                self.assertEqual(result["status"], "partial")
                self.assertEqual(calls, ["file"])
                self.assertTrue(result["can_retry"])
                self.assertIn("confirmed evidence", str(result["evidence"]))
                self.assertEqual(orchestrator.load_thread_history(), [{"role":"user","content":"read"}])
                with self.assertRaises(ValueError):
                    orchestrator.invoke("read again")
                result = orchestrator._result(orchestrator.retry_stream())
                self.assertEqual(result["answer"], "done")
                self.assertEqual(calls, ["file"])
            finally:
                orchestrator.close()

    def test_model_context_is_bounded_on_every_turn_but_history_is_retained(self):
        seen = []
        original = ScriptedModel._generate
        def record(model, messages, *args, **kwargs):
            seen.append(messages)
            return original(model, messages, *args, **kwargs)
        with TemporaryDirectory() as directory:
            agent = BaseAgent(ScriptedModel(responses=[AIMessage(content="ok") for _ in range(4)]), prompt="test", config=AgentConfig(max_history_messages=3))
            orchestrator = AgentOrchestrator(config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"), agent=agent)
            try:
                with patch.object(ScriptedModel, "_generate", record):
                    for task in ["one", "two", "three", "four"]:
                        orchestrator.invoke(task)
                self.assertTrue(all(len([m for m in messages if m.type != "system"]) <= 3 for messages in seen))
                self.assertEqual(len(orchestrator._snapshot().values["messages"]), 8)
                self.assertEqual(len(orchestrator.load_thread_history()), 8)
            finally:
                orchestrator.close()

    def test_no_previous_answer_is_returned_for_incomplete_turn(self):
        self.assertEqual(final_answer([HumanMessage(content="old"),AIMessage(content="old answer"),HumanMessage(content="new")]), "")


if __name__ == "__main__":
    unittest.main()
