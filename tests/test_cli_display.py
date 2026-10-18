"""CLI-only regression coverage for input, queue, review and resource browsing."""

import io
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
import unittest
from unittest.mock import patch

from rich.console import Console

from platon.cli_display import ModernTerminal, suggestions, splash
from platon.run_agent_chat import TerminalClient
from tests.test_agent_chat_terminal import FakeAgent


class ModernTerminalTests(unittest.TestCase):
    def client(self, agent=None, *, width=110, height=40):
        console = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        client = ModernTerminal(agent or FakeAgent(), console=console)
        self.addCleanup(client.close)
        return client

    def wait_for(self, client, predicate):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            client.pump()
            if predicate():
                return
            Event().wait(.005)
        self.fail("CLI did not reach expected state")

    def test_queue_accepts_input_while_running_and_runs_fifo(self):
        agent = FakeAgent()
        started, release = Event(), Event()
        self.addCleanup(release.set)
        messages = []
        def stream(message, *, stop_event=None):
            messages.append(message)
            if len(messages) == 1:
                started.set()
                release.wait(2)
            yield from agent._completed(message)
        agent.stream = stream
        client = self.client(agent)
        client.submit("pierwsze")
        client.pump()
        self.assertTrue(started.wait(1))
        client.submit("drugie")
        self.assertEqual(client.message_queue, ["drugie"])
        release.set()
        self.wait_for(client, lambda: not client.busy and not client.message_queue)
        self.assertEqual(messages, ["pierwsze", "drugie"])

    def test_stop_signals_worker_and_retains_queue_until_explicit_resume(self):
        agent = FakeAgent()
        started = Event()
        def stream(message, *, stop_event=None):
            agent.last_message = message
            if message == "długie":
                started.set()
                if not stop_event.wait(2):
                    raise RuntimeError("stop never arrived")
                yield {"type": "result", "data": {"status": "stopped"}}
            else:
                yield from agent._completed()
        agent.stream = stream
        client = self.client(agent)
        client.submit("długie")
        client.pump()
        self.assertTrue(started.wait(1))
        client.submit("następne")
        client.submit("/stop")
        self.wait_for(client, lambda: not client.busy)
        self.assertTrue(agent.stopped)
        self.assertTrue(client.paused)
        self.assertEqual(client.message_queue, ["następne"])
        client.submit("/queue run")
        self.wait_for(client, lambda: not client.busy and not client.message_queue)
        self.assertEqual(agent.last_message, "następne")

    def test_exception_pauses_queue(self):
        agent = FakeAgent()
        def fail(*args, **kwargs):
            raise RuntimeError("offline")
        agent.stream = fail
        client = self.client(agent)
        client.submit("pierwsze")
        client.submit("drugie")
        self.wait_for(client, lambda: client.paused and not client.busy)
        self.assertEqual(client.message_queue, ["drugie"])
        self.assertIn("offline", client.transcript)

    def test_review_uses_separate_input_and_restores_unsent_draft(self):
        agent = FakeAgent(pending=[{"id": "q", "value": {"kind": "clarification", "question": "Który plik?"}}])
        client = self.client(agent)
        client.draft = "niewysłane zadanie"
        client.start_job(client.review_pending)
        self.wait_for(client, lambda: bool(client.question))
        self.assertEqual(client.draft, "")
        self.assertEqual(client.saved_draft, "niewysłane zadanie")
        client.submit("raport.pdf")
        self.wait_for(client, lambda: not client.busy)
        self.assertEqual(agent.last_decisions, {"q": {"answer": "raport.pdf"}})
        self.assertEqual(client.draft, "niewysłane zadanie")
        self.assertEqual(client.message_queue, [])

    def test_stop_cancels_review_without_approving_it(self):
        agent = FakeAgent(pending=[{"id": "q", "value": {"action_requests": [{"name": "write", "args": {}}]}}])
        client = self.client(agent)
        client.start_job(client.review_pending)
        self.wait_for(client, lambda: bool(client.question))
        client.submit("/stop")
        self.wait_for(client, lambda: not client.busy)
        self.assertTrue(agent.discarded)
        self.assertIsNone(agent.last_decisions)
        self.assertTrue(client.paused)

    def test_completions_editor_and_pets(self):
        client = self.client()
        for char in "/mem":
            client.key(char)
        self.assertEqual(suggestions(client.draft), ["/memory"])
        client.key("TAB")
        self.assertEqual(client.draft, "/memory ")
        client.key("CLEAR")
        client.key("ą")
        client.key("NEWLINE")
        client.key("b")
        self.assertEqual(client.draft, "ą\nb")
        client.submit("/pets kot")
        self.assertEqual(client.pet, "kot")
        client.submit("/pets off")
        self.assertEqual(client.pet, "off")

    def test_render_wide_and_small_terminal_with_untrusted_text(self):
        for width, height in [(110, 40), (60, 24)]:
            with self.subTest(width=width):
                client = self.client(width=width, height=height)
                client._print("[red]literal[/red]\x1b[2J\n" + "line\n" * 100)
                client.pump()
                client.key("PAGEUP")
                client.console.print(client.render())
                output = client.console.file.getvalue()
                self.assertIn("PLATON CLI", output)
                self.assertIn("WIADOMOŚĆ", output)
                self.assertNotIn("\x1b", output)
                self.assertEqual(len(output.splitlines()), height)
                self.assertTrue(all(len(line) <= width for line in output.splitlines()))

    def test_pending_state_blocks_queued_messages_until_resumed(self):
        agent = FakeAgent(retry=True)
        client = self.client(agent)
        client.start_job(lambda: None)
        self.wait_for(client, lambda: not client.busy)
        client.submit("później")
        client.submit("/queue run")
        client.pump()
        self.assertFalse(client.busy)
        self.assertEqual(client.message_queue, ["później"])

    def test_splash_is_renderable_at_small_width(self):
        console = Console(file=io.StringIO(), width=50, color_system=None)
        console.print(splash(.25, 50))
        self.assertIn("Inicjalizacja", console.file.getvalue())

    def test_interactive_loop_processes_commands_and_exits_cleanly(self):
        client = self.client()
        keys = iter([*"/pets kot", "ENTER", *"/help", "ENTER", *"/exit", "ENTER"])
        with patch("platon.cli_display.Keyboard.open") as opened, patch(
            "platon.cli_display.Keyboard.read", side_effect=lambda: next(keys, None)
        ):
            self.assertEqual(client.interactive(), 0)
            opened.assert_called_once()
        self.assertFalse(client.busy)
        self.assertEqual(client.pet, "kot")

    def test_plain_mode_supports_pet_selection_without_full_screen(self):
        output = io.StringIO()
        client = TerminalClient(FakeAgent(), out=output, color=False)
        client.handle_command("/pets lis")
        client.handle_command("/pet")
        self.assertIn("Kompan: lis", output.getvalue())
        self.assertIn("V", output.getvalue())

    def test_real_graph_queue_persists_both_conversation_turns(self):
        from langchain_core.messages import AIMessage
        from platon.agent.agent_orchestrator import AgentOrchestrator
        from platon.agent.base_agent import BaseAgent
        from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig
        from tests.test_agent_workflows import ScriptedModel

        with TemporaryDirectory() as directory:
            agent = AgentOrchestrator(
                config=AgentOrchestratorConfig(sqlite_path=Path(directory) / "chat.sqlite3"),
                agent=BaseAgent(ScriptedModel(responses=[AIMessage(content="Pierwsza odpowiedź"),
                                                       AIMessage(content="Druga odpowiedź")]), prompt="test"),
            )
            client = self.client(agent)
            try:
                client.submit("pierwsze")
                client.submit("drugie")
                self.wait_for(client, lambda: not client.busy and not client.message_queue)
                history = agent.load_thread_history()
                self.assertEqual([message["content"] for message in history],
                                 ["pierwsze", "Pierwsza odpowiedź", "drugie", "Druga odpowiedź"])
                self.assertIn("Druga odpowiedź", client.transcript)
            finally:
                client.close()


class ContextFilesTests(unittest.TestCase):
    def test_virtual_paths_use_agent_root_and_cannot_escape_it(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "agent"
            (root / "skills" / "research").mkdir(parents=True)
            (root / "memory").mkdir()
            (root / "skills" / "research" / "SKILL.md").write_text("# Research", encoding="utf-8")
            (root / "memory" / "AGENTS.md").write_text("# Context\nPolski: ąę\x1b[2J", encoding="utf-8")
            (Path(directory) / "outside.md").write_text("secret", encoding="utf-8")
            agent = FakeAgent()
            agent.agent_config.backend_root = root
            agent.agent_config.skills = ["/skills/"]
            agent.agent_config.memory = ["/memory/AGENTS.md", "/../outside.md"]
            output = io.StringIO()
            client = TerminalClient(agent, out=output, color=False)
            self.assertEqual([path for path, _ in client.context_files("skills")], ["/skills/research/SKILL.md"])
            self.assertEqual([path for path, _ in client.context_files("memory")], ["/memory/AGENTS.md"])
            client.handle_command("/memory 1")
            self.assertIn("Polski: ąę", output.getvalue())
            self.assertNotIn("\x1b", output.getvalue())
            self.assertNotIn("secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
