"""Verify the coding SDK tools share a root and retain mutation review."""

import json
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
    def test_skills_reach_coding_without_skill_instructions_in_task(self):
        for configured_sources in (None, [], ["/custom-skills/"]):
            with self.subTest(sources=configured_sources), TemporaryDirectory() as directory:
                root = Path(directory)
                source = configured_sources[0] if configured_sources else "/skills/"
                for name in ("docx", "pdf", "pptx"):
                    folder = root / source.strip("/") / name
                    folder.mkdir(parents=True)
                    (folder / "SKILL.md").write_text(
                        f"---\nname: {name}\ndescription: {name} test capability\n---\n"
                        f"{name} workflow marker\n", encoding="utf-8",
                    )
                options = {} if configured_sources is None else {"skills": configured_sources}
                supplied_config = AgentConfig(backend_root=root, memory=[], debug=False, **options)
                agent = CodingAgent(
                    ScriptedModel(responses=[
                        call("read_file", file_path=f"{source}docx/SKILL.md"),
                        AIMessage(content="done"),
                    ]), root, config=supplied_config,
                )
                assignment = json.dumps({
                    "user_request": "Create a short DOCX in Polish",
                    "original_request": "Create a short DOCX in Polish",
                    "task": "Create a short DOCX in Polish",
                    "retry_reason": "", "dependency_evidence": [],
                })
                with patch.object(ScriptedModel, "_generate", autospec=True,
                                  side_effect=ScriptedModel._generate) as generate:
                    result = agent.invoke(assignment)
                self.assertEqual({skill["name"] for skill in result["skills_metadata"]},
                                 {"docx", "pdf", "pptx"})
                model_messages = str(generate.call_args_list[0].args[1])
                for name in ("docx", "pdf", "pptx"):
                    self.assertIn(f"{name} test capability", model_messages)
                skill_read = next(m for m in result["messages"] if isinstance(m, ToolMessage))
                self.assertEqual(skill_read.status, "success")
                self.assertIn("docx workflow marker", str(skill_read.content))
                self.assertEqual(agent.config.skills, [source])
                self.assertEqual(supplied_config.skills,
                                 ["/skills/"] if configured_sources is None else configured_sources)
                if configured_sources == []:
                    self.assertIsNot(agent.config, supplied_config)
                else:
                    self.assertIs(agent.config, supplied_config)

    def test_sdk_reads_and_host_execution_use_backend_root(self):
        with TemporaryDirectory() as directory:
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

            agent = CodingAgent(
                ScriptedModel(responses=[
                    call("read_file", file_path="/source.py"),
                    call("run_python", code="from pathlib import Path; print(Path.cwd())"),
                    AIMessage(content="done"),
                ]), other,
                config=AgentConfig(backend_root=root, skills=[], memory=[], debug=False),
                checkpointer=InMemorySaver(),
            )
            self.assertEqual({tool.name for tool in agent.tools_list}, {
                "copy_file", "move_file", "run_shell", "run_python", "create_venv", "delete_venv",
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
