"""Supervisor must route document reads through the database specialist."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from platon.agent.agents.supervisor_agent import DocumentReadGuard, SupervisorAgent
from platon.agent.models.agent_config import AgentConfig


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class DocumentReadGuardTests(unittest.TestCase):
    def test_blocks_pdf_and_document_directory_before_reading(self) -> None:
        guard = DocumentReadGuard()
        calls = []

        for path in ("/documents/book.pdf", "C:\\books\\book.PDF", "/documents/book.txt"):
            with self.subTest(path=path):
                request = SimpleNamespace(tool_call={
                    "name": "read_file", "args": {"file_path": path}, "id": "read-1",
                })
                result = guard.wrap_tool_call(request, lambda _: calls.append(path))
                self.assertIsInstance(result, ToolMessage)
                self.assertEqual(result.status, "error")
                self.assertIn("delegate_database", result.content)

        self.assertEqual(calls, [])

    def test_allows_skills_and_other_tools(self) -> None:
        guard = DocumentReadGuard()
        expected = ToolMessage(content="ok", tool_call_id="read-2")
        for name, path in (("read_file", "/skills/SKILL.md"),
                           ("delegate_database", "/documents/book.pdf")):
            request = SimpleNamespace(tool_call={
                "name": name, "args": {"file_path": path}, "id": "read-2",
            })
            self.assertIs(guard.wrap_tool_call(request, lambda _: expected), expected)

    def test_supervisor_does_not_open_pdf(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "documents" / "book.pdf"
            document.parent.mkdir()
            document.write_bytes(b"%PDF-1.4\nprivate bytes")
            model = ScriptedModel(responses=[
                AIMessage(content="", tool_calls=[{
                    "name": "read_file", "args": {"file_path": "/documents/book.pdf"},
                    "id": "read-3", "type": "tool_call",
                }]),
                AIMessage(content="Cannot read directly."),
            ])
            supervisor = SupervisorAgent(
                model, {}, config=AgentConfig(backend_root=root, skills=[], memory=[]),
                prompt="Route document reads through the database specialist.",
            )
            result = supervisor.invoke("Analyze book.pdf")

            response = next(message for message in result["messages"]
                            if isinstance(message, ToolMessage) and message.name == "read_file")
            self.assertEqual(response.status, "error")
            self.assertIn("delegate_database", response.content)
            self.assertNotIn("private bytes", str(response.content))


if __name__ == "__main__":
    unittest.main()
