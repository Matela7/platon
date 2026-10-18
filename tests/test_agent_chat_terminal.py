"""Focused tests for the terminal presentation layer."""

import io
import json
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from platon.run_agent_chat import TerminalClient


class FakeAgent:
    def __init__(self, thread_id="thread-one", *, pending=None, retry=False):
        self.thread_id = thread_id
        self.agent_config = SimpleNamespace(model_name="test-model")
        self.pending = list(pending or [])
        self.retry = retry
        self.closed = False
        self.discarded = False
        self.stopped = False
        self.last_message = None
        self.last_decisions = None

    @staticmethod
    def _completed(answer="Gotowe"):
        yield {"type": "delta", "data": answer}
        yield {"type": "result", "data": {
            "status": "completed", "answer": answer, "errors": [],
            "interrupts": [], "can_retry": False, "elapsed_seconds": 0.25,
        }}

    def stream(self, message, *, stop_event=None):
        self.last_message = message
        yield {"type": "progress", "data": {"tool": "search", "status": "success"}}
        yield from self._completed()

    def resume_stream(self, decisions, *, stop_event=None):
        self.last_decisions = decisions
        self.pending.clear()
        yield from self._completed("Wznowiono")

    def retry_stream(self, *, stop_event=None):
        self.retry = False
        yield from self._completed("Ponowiono")

    def pending_interrupts(self):
        return list(self.pending)

    def can_retry(self):
        return self.retry

    def discard_pending_run(self):
        changed = bool(self.pending or self.retry)
        self.pending.clear()
        self.retry = False
        self.discarded = changed
        return changed

    def load_thread_history(self):
        return [{"role": "user", "content": "Cześć"}]

    def list_threads(self):
        return [
            {"thread_id": "thread-one", "title": "Pierwsza", "message_count": 2},
            {"thread_id": "thread-two", "title": "Druga", "message_count": 4},
        ]

    def stop(self):
        self.stopped = True
        return True

    def close(self):
        self.closed = True


class TerminalClientTests(unittest.TestCase):
    def client(self, agent=None, *, answers=(), json_mode=False, factory=None):
        output, errors = io.StringIO(), io.StringIO()
        replies = iter(answers)
        client = TerminalClient(
            agent or FakeAgent(), out=output, err=errors,
            input_fn=lambda _: next(replies), color=False, json_mode=json_mode,
            agent_factory=factory or (lambda thread_id: FakeAgent(thread_id)),
        )
        return client, output, errors

    def test_stream_renders_progress_delta_and_result(self):
        agent = FakeAgent()
        client, output, _ = self.client(agent)

        result = client.run_stream(lambda stop: agent.stream("test", stop_event=stop))

        rendered = output.getvalue()
        self.assertEqual(result["status"], "completed")
        self.assertIn("✓ search [success]", rendered)
        self.assertIn("Platon  Gotowe", rendered)
        self.assertIn("completed · 0.25s", rendered)
        self.assertNotIn("\033[", rendered)

    def test_nonstreamed_answer_is_not_lost(self):
        client, output, _ = self.client()

        client.run_stream(lambda _: iter([{"type": "result", "data": {
            "status": "completed", "answer": "Finalna odpowiedź", "errors": [],
        }}]))

        self.assertIn("Platon  Finalna odpowiedź", output.getvalue())

    def test_clarification_resumes_with_exact_interrupt_shape(self):
        pending = [{"id": "ask-1", "value": {"kind": "clarification", "question": "Który plik?"}}]
        agent = FakeAgent(pending=pending)
        client, output, _ = self.client(agent, answers=["raport.pdf"])

        client.review_pending()

        self.assertEqual(agent.last_decisions, {"ask-1": {"answer": "raport.pdf"}})
        self.assertIn("Wznowiono", output.getvalue())

    def test_approval_supports_rejection(self):
        pending = [{"id": "review-1", "value": {"action_requests": [{
            "name": "write_file", "description": "Zapis pliku", "args": {"path": "a.txt"},
        }]}}]
        agent = FakeAgent(pending=pending)
        client, _, _ = self.client(agent, answers=["n"])

        client.review_pending()

        self.assertEqual(agent.last_decisions, {
            "review-1": {"decisions": [{"type": "reject"}]}
        })

    def test_session_switch_closes_old_agent(self):
        old = FakeAgent()
        created = []
        def factory(thread_id):
            created.append(thread_id)
            return FakeAgent(thread_id)
        client, output, _ = self.client(old, factory=factory)

        self.assertTrue(client.handle_command("/switch 2"))

        self.assertEqual(created, ["thread-two"])
        self.assertTrue(old.closed)
        self.assertEqual(client.agent.thread_id, "thread-two")
        self.assertIn("Aktywny wątek", output.getvalue())

    def test_retry_and_discard_commands(self):
        agent = FakeAgent(retry=True)
        client, output, _ = self.client(agent)
        client.handle_command("/retry")
        agent.retry = True
        client.handle_command("/discard")

        self.assertTrue(agent.discarded)
        self.assertIn("Ponowiono", output.getvalue())
        self.assertIn("Porzucono", output.getvalue())

    def test_json_mode_emits_backend_events_as_jsonl(self):
        agent = FakeAgent()
        client, output, _ = self.client(agent, json_mode=True)

        exit_code = client.one_shot("test")

        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(exit_code, 0)
        self.assertEqual([event["type"] for event in events], ["progress", "delta", "result"])

    def test_ctrl_c_requests_cooperative_stop_and_waits_for_result(self):
        real_queue = queue.Queue

        class InterruptOnceQueue:
            def __init__(self):
                self.inner = real_queue()
                self.interrupted = False

            def put(self, item):
                self.inner.put(item)

            def get(self, timeout=None):
                if not self.interrupted:
                    self.interrupted = True
                    raise KeyboardInterrupt
                return self.inner.get(timeout=timeout)

            def empty(self):
                return self.inner.empty()

        agent = FakeAgent()
        client, output, _ = self.client(agent)

        def operation(stop_event):
            self.assertTrue(stop_event.wait(1))
            yield {"type": "result", "data": {
                "status": "stopped", "answer": "", "errors": [], "can_retry": False,
            }}

        with patch("platon.run_agent_chat.queue.Queue", InterruptOnceQueue):
            result = client.run_stream(operation)

        self.assertTrue(agent.stopped)
        self.assertEqual(result["status"], "stopped")
        self.assertIn("Zatrzymywanie aktywnego zadania", output.getvalue())

    def test_queue_runs_fifo(self):
        agent = FakeAgent()
        seen = []
        original_stream = agent.stream
        def stream(message, *, stop_event=None):
            seen.append(message)
            yield from original_stream(message, stop_event=stop_event)
        agent.stream = stream
        client, _, errors = self.client(agent)
        client.handle_command("/queue add pierwsze")
        client.handle_command("/queue add drugie")
        client.handle_command("/queue run")
        self.assertEqual(seen, ["pierwsze", "drugie"])
        self.assertEqual(client.message_queue, [])
        self.assertEqual(errors.getvalue(), "")

    def test_queue_pauses_on_stop_and_keeps_remaining_messages(self):
        agent = FakeAgent()
        agent.stream = lambda *args, **kwargs: iter([{
            "type": "result", "data": {"status": "stopped", "answer": ""},
        }])
        client, output, _ = self.client(agent)
        client.message_queue.extend(["pierwsze", "drugie"])
        client.handle_command("/queue run")
        self.assertEqual(client.message_queue, ["drugie"])
        self.assertIn("Kolejka wstrzymana", output.getvalue())

    def test_queue_waits_for_unfinished_run_without_consuming_message(self):
        agent = FakeAgent(retry=True)
        client, _, _ = self.client(agent)
        client.message_queue.append("później")
        client.handle_command("/queue run")
        self.assertIsNone(agent.last_message)
        self.assertEqual(client.message_queue, ["później"])

    def test_queue_cannot_leak_into_another_conversation(self):
        agent = FakeAgent()
        client, _, errors = self.client(agent)
        client.message_queue.append("zadanie")
        client.handle_command("/new")
        client.handle_command("/switch 2")
        self.assertIs(client.agent, agent)
        self.assertFalse(agent.closed)
        self.assertIn("/queue clear", errors.getvalue())

    def test_failed_thread_initialization_keeps_cli_and_old_agent(self):
        def factory(thread_id):
            raise RuntimeError("cannot open database")
        agent = FakeAgent()
        client, _, errors = self.client(agent, factory=factory)
        self.assertTrue(client.handle_command("/new"))
        self.assertIs(client.agent, agent)
        self.assertFalse(agent.closed)
        self.assertIn("cannot open database", errors.getvalue())

    def test_resume_command_returns_to_pending_question(self):
        agent = FakeAgent(pending=[{
            "id": "question", "value": {"kind": "clarification", "question": "Co wybrać?"},
        }])
        client, _, _ = self.client(agent, answers=["A"])
        client.handle_command("/resume")
        self.assertEqual(agent.last_decisions, {"question": {"answer": "A"}})

    def test_final_answer_not_lost_when_stream_contains_only_intermediate_text(self):
        client, output, _ = self.client()
        client.run_stream(lambda _: iter([
            {"type": "delta", "data": "Sprawdzam dane…"},
            {"type": "result", "data": {"status": "completed", "answer": "Wynik: 42"}},
        ]))
        self.assertIn("Wynik: 42", output.getvalue())

    def test_queue_continues_after_answered_clarification(self):
        agent = FakeAgent()
        def stream(message, *, stop_event=None):
            if message == "pierwsze":
                agent.pending = [{"id": "q", "value": {"kind": "clarification", "question": "Który?"}}]
                yield {"type": "result", "data": {"status": "interrupted", "interrupts": agent.pending}}
            else:
                agent.last_message = message
                yield from agent._completed()
        agent.stream = stream
        client, _, _ = self.client(agent, answers=["A"])
        client.message_queue.extend(["pierwsze", "drugie"])
        client.handle_command("/queue run")
        self.assertEqual(agent.last_message, "drugie")
        self.assertEqual(client.message_queue, [])


if __name__ == "__main__":
    unittest.main()
