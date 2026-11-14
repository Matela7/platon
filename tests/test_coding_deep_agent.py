"""Verify the coding SDK tools share a root and retain mutation review."""

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from platon.agent.agents.coding_agent import CodingAgent
from platon.agent.models.agent_config import AgentConfig


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def call(name, **args):
    return AIMessage(content="", tool_calls=[{
        "name": name, "args": args, "id": name, "type": "tool_call",
    }])


class CodingDeepAgentTests(unittest.TestCase):
    def test_sdk_reads_and_host_execution_use_backend_root_in_both_versions(self):
        copy_path = Path(__file__).parents[1] / "src/platon/agent/agents/coding_agent copy.py"
        spec = importlib.util.spec_from_file_location("coding_agent_copy", copy_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for agent_type in (CodingAgent, module.CodingAgent):
            with self.subTest(agent=agent_type.__module__), TemporaryDirectory() as directory:
                root = Path(directory) / "backend"
                root.mkdir()
                (root / "source.py").write_text("backend marker", encoding="utf-8")
                other = Path(directory) / "other"
                other.mkdir()
                (other / "source.py").write_text("wrong marker", encoding="utf-8")
                exposed = []

                def bind_tools(model, tools, **kwargs):
                    exposed.append([tool.name for tool in tools])
                    return model

                agent = agent_type(
                    ScriptedModel(responses=[
                        call("read_file", file_path="/source.py"),
                        call("run_python", code="from pathlib import Path; print(Path.cwd())"),
                        AIMessage(content="done"),
                    ]), other,
                    config=AgentConfig(backend_root=root, skills=[], memory=[], debug=False),
                    checkpointer=InMemorySaver(),
                )
                self.assertEqual({tool.name for tool in agent.tools_list}, {
                    "copy_file", "move_file", "run_shell", "run_python",
                })
                config = {"configurable": {"thread_id": "root"}}
                with patch.object(ScriptedModel, "bind_tools", bind_tools):
                    result = agent.invoke("Read source and show the execution directory", config=config)
                    self.assertIn("__interrupt__", result)
                    result = agent.invoke(Command(resume={
                        "decisions": [{"type": "approve"}],
                    }), config=config)
                outputs = {m.name: str(m.content) for m in result["messages"]
                           if isinstance(m, ToolMessage)}
                self.assertIn("backend marker", outputs["read_file"])
                self.assertNotIn("wrong marker", outputs["read_file"])
                self.assertEqual(Path(outputs["run_python"].strip()), root)
                for names in exposed:
                    self.assertEqual(len(names), len(set(names)))
                    self.assertTrue({"ls", "read_file", "write_file", "edit_file", "delete",
                                     "glob", "grep"}.issubset(names))
                    self.assertTrue({"file_search", "list_directory", "file_delete", "execute"}
                                    .isdisjoint(names))
                self.assertFalse((root / "shared").exists())

    def test_sdk_mutations_wait_for_approval(self):
        cases = [
            ("write_file", {"file_path": "/new.txt", "content": "new"}, "approve"),
            ("edit_file", {"file_path": "/existing.txt", "old_string": "old",
                           "new_string": "new"}, "approve"),
            ("delete", {"file_path": "/existing.txt"}, "reject"),
        ]
        for name, args, decision in cases:
            with self.subTest(tool=name), TemporaryDirectory() as directory:
                root = Path(directory)
                existing = root / "existing.txt"
                existing.write_text("old", encoding="utf-8")
                agent = CodingAgent(
                    ScriptedModel(responses=[call(name, **args), AIMessage(content="done")]),
                    root, config=AgentConfig(backend_root=root, skills=[], memory=[], debug=False),
                    checkpointer=InMemorySaver(),
                )
                config = {"configurable": {"thread_id": name}}
                result = agent.invoke("Perform the file operation", config=config)
                self.assertIn("__interrupt__", result)
                self.assertEqual(existing.read_text(encoding="utf-8"), "old")
                self.assertFalse((root / "new.txt").exists())
                result = agent.invoke(Command(resume={
                    "decisions": [{"type": decision}],
                }), config=config)
                self.assertEqual(result["messages"][-1].content, "done")
                if name == "write_file":
                    self.assertEqual((root / "new.txt").read_text(encoding="utf-8"), "new")
                else:
                    self.assertEqual(existing.read_text(encoding="utf-8"),
                                     "new" if name == "edit_file" else "old")


if __name__ == "__main__":
    unittest.main()
