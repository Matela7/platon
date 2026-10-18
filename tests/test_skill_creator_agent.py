"""Exercise skill discovery, dedicated routing and filesystem scope on real graphs."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from platon.agent.agents.skill_creator_agent import SkillCreatorAgent
from platon.agent.agents.supervisor_agent import SupervisorAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from tests.test_deep_agent import ScriptedModel


def call(name, args, identifier):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": identifier}])


class SkillCreatorTests(unittest.TestCase):
    def test_supervisor_delegates_and_skill_is_discovered_next_run(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            creator = root / "skills/skill-creator"
            creator.mkdir(parents=True)
            (creator / "SKILL.md").write_text(
                "---\nname: skill-creator\ndescription: Create reusable skills.\n---\nUse concise instructions.\n",
                encoding="utf-8",
            )
            skill = "---\nname: test-skill\ndescription: Marker for future tasks.\n---\nFollow this workflow.\n"
            model = ScriptedModel(responses=[
                call("delegate_skill_creator", {"user_request": "Create a test skill"}, "delegate"),
                call("read_file", {"file_path": "/skills/skill-creator/SKILL.md"}, "guide"),
                call("write_file", {"file_path": "/skills/test-skill/SKILL.md", "content": skill}, "write"),
                call("read_file", {"file_path": "/skills/test-skill/SKILL.md"}, "verify"),
                AIMessage(content="Created /skills/test-skill/SKILL.md"),
                AIMessage(content="Skill created."),
                AIMessage(content="Ready."),
            ])
            supervisor = SupervisorAgent.from_config(
                AgentConfig(backend_root=root), AgentOrchestratorConfig(working_dir=root), model=model,
            )
            result = supervisor.invoke("Create a test skill")
            self.assertEqual((root / "skills/test-skill/SKILL.md").read_text(encoding="utf-8"), skill)
            delegated = next(message for message in result["messages"]
                             if isinstance(message, ToolMessage) and message.name == "delegate_skill_creator")
            self.assertEqual(delegated.artifact["status"], "completed")
            with patch.object(ScriptedModel, "_generate", autospec=True,
                              side_effect=ScriptedModel._generate) as generate:
                supervisor.invoke("What skills are available?")
            self.assertIn("Marker for future tasks.", str(generate.call_args.args[1]))

    def test_outside_reads_writes_and_delegation_are_blocked(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            memory = root / "memory/AGENTS.md"
            memory.parent.mkdir()
            memory.write_text("PRIVATE MEMORY MARKER", encoding="utf-8")
            document = root / "documents/source.txt"
            document.parent.mkdir()
            document.write_text("PRIVATE DOCUMENT MARKER", encoding="utf-8")
            responses = [
                call("read_file", {"file_path": "/memory/AGENTS.md"}, "read"),
                call("read_file", {"file_path": "/documents/source.txt"}, "document"),
                call("write_file", {"file_path": "/memory/new.md", "content": "bad"}, "write"),
                call("write_file", {"file_path": "/skills/../memory/AGENTS.md", "content": "bad"}, "traversal"),
                call("task", {"subagent_type": "general-purpose", "description": "Write /memory/new.md"}, "task"),
                call("execute", {"command": "echo bad"}, "execute"),
                AIMessage(content="Stopped."),
            ]
            model = ScriptedModel(responses=responses)
            with patch.object(ScriptedModel, "bind_tools", autospec=True,
                              side_effect=ScriptedModel.bind_tools) as bind:
                result = SkillCreatorAgent(model, config=AgentConfig(backend_root=root)).invoke("Create a skill")
            bound_tools = {tool.name for tool in bind.call_args.args[1]}
            self.assertTrue({"read_file", "write_file", "edit_file"}.issubset(bound_tools))
            self.assertNotIn("task", bound_tools)
            self.assertNotIn("execute", bound_tools)
            tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
            self.assertEqual(len(tool_messages), 6)
            self.assertTrue(all(message.status == "error" or "Error" in str(message.content)
                                or "denied" in str(message.content).lower() for message in tool_messages))
            self.assertNotIn("PRIVATE MEMORY MARKER", str(result))
            self.assertNotIn("PRIVATE DOCUMENT MARKER", str(result))
            self.assertFalse((root / "memory/new.md").exists())
            self.assertFalse((root / "escape.md").exists())
            self.assertEqual(memory.read_text(encoding="utf-8"), "PRIVATE MEMORY MARKER")


if __name__ == "__main__":
    unittest.main()
