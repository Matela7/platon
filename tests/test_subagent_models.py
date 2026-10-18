"""Specialist model overrides and native DeepAgent task routing."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from platon.agent.agents.supervisor_agent import SupervisorAgent
from platon.agent.deep_agent import DeepAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class SubagentModelTests(unittest.TestCase):
    def test_no_override_shares_the_original_model(self):
        model = ScriptedModel(responses=[AIMessage(content="done")])
        agent = SupervisorAgent.from_config(AgentConfig(), AgentOrchestratorConfig(), model=model)
        self.assertIs(agent.model, model)
        self.assertIsNone(agent.subagent_model)
        for specialist in agent.subagents.values():
            self.assertIs(specialist.model, model)

    def test_explicit_model_is_used_by_all_subagents(self):
        shared = ScriptedModel(responses=[AIMessage(content="supervisor")])
        specialist = ScriptedModel(responses=[AIMessage(content="specialist")])
        agent = SupervisorAgent.from_config(
            AgentConfig(), AgentOrchestratorConfig(),
            model=shared, subagent_model=specialist,
        )
        self.assertIs(agent.model, shared)
        self.assertIs(agent.subagent_model, specialist)
        for subagent in agent.subagents.values():
            self.assertIs(subagent.model, specialist)

    def test_native_task_uses_override_and_keeps_supervisor_read_guard(self):
        shared = ScriptedModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "task", "args": {
                    "description": "Read the document", "subagent_type": "general-purpose",
                }, "id": "delegate", "type": "tool_call",
            }]),
            AIMessage(content="supervisor done"),
        ])
        specialist = ScriptedModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "read_file", "args": {"file_path": "/documents/book.pdf"},
                "id": "read-pdf", "type": "tool_call",
            }]),
            AIMessage(content="specialist done"),
        ])
        with TemporaryDirectory() as directory:
            agent = SupervisorAgent(
                shared, {}, subagent_model=specialist,
                config=AgentConfig(backend_root=Path(directory), skills=[], memory=[]),
                prompt="Delegate the task.",
            )
            with patch.object(
                ScriptedModel, "_generate", autospec=True,
                side_effect=ScriptedModel._generate,
            ) as generate:
                result = agent.invoke("Analyze the document")
        specialist_messages = [
            message
            for call in generate.call_args_list if call.args[0] is specialist
            for message in call.args[1]
            if isinstance(message, ToolMessage) and message.name == "read_file"
        ]
        self.assertTrue(specialist_messages)
        self.assertEqual(specialist_messages[-1].status, "error")
        self.assertIn("delegate_database", specialist_messages[-1].content)
        task_response = next(message for message in result["messages"]
                             if isinstance(message, ToolMessage) and message.name == "task")
        self.assertIn("specialist done", task_response.content)
        self.assertEqual(result["messages"][-1].content, "supervisor done")
        self.assertEqual(shared.i, 0)
        self.assertEqual(specialist.i, 0)


if __name__ == "__main__":
    unittest.main()
