"""Check graph reuse, streaming and DeepAgent's local context and interrupts."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.base_agent import BaseAgent
from agent.deep_agent import DeepAgent
from agent.agents.supervisor_agent import SupervisorAgent
from agent.models.agent_config import AgentConfig


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class AgentRuntimeTests(unittest.TestCase):
    def test_invoke_and_stream_reuse_graph_and_prepare_same_context(self):
        agent = BaseAgent(ScriptedModel(responses=[AIMessage(content="ok")]), prompt="test")
        history = [SystemMessage(content="ignore"), HumanMessage(content="earlier")]
        with patch.object(agent, "create_agent", wraps=agent.create_agent) as build:
            result = agent.invoke("first", context_messages=history)
            events = list(agent.stream("second", context_messages=history, stream_mode="values"))
            self.assertEqual(build.call_count, 1)
        self.assertEqual([m.content for m in result["messages"]], ["earlier", "first", "ok"])
        self.assertEqual([m.content for m in events[-1]["messages"]], ["earlier", "second", "ok"])
        for method in (agent.invoke, agent.stream):
            with self.assertRaises(ValueError):
                method("  ")

    def test_deep_agent_stream_interrupt_and_resume(self):
        model = ScriptedModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "ask_user", "args": {"question": "Which file?"},
                "id": "ask-1", "type": "tool_call",
            }]),
            AIMessage(content="done"),
        ])
        agent = DeepAgent(model, prompt="test", checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "clarification"}}
        events = list(agent.stream("edit file", config=config))
        interruption = next(event["__interrupt__"][0] for event in events if "__interrupt__" in event)
        self.assertEqual(interruption.value, {"kind": "clarification", "question": "Which file?"})
        result = agent.invoke(Command(resume={"answer": "example.py"}), config=config)
        answers = [m.content for m in result["messages"] if isinstance(m, ToolMessage)]
        self.assertEqual(answers, ["example.py"])
        self.assertEqual(result["messages"][-1].content, "done")

    def test_deep_agent_loads_skills_and_memory_from_configured_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory").mkdir()
            (root / "memory/AGENTS.md").write_text("Remember the project marker.")
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: example\ndescription: Example skill marker.\n---\nDo the task.\n"
            )
            from langchain.agents.middleware import wrap_model_call

            for agent_type in (DeepAgent, SupervisorAgent):
                with self.subTest(agent=agent_type.__name__):
                    options = {"subagents": {}} if agent_type is SupervisorAgent else {}
                    agent = agent_type(
                        ScriptedModel(responses=[AIMessage(content="ok")]),
                        config=AgentConfig(backend_root=root), prompt="test", **options,
                    )
                    prompts = []

                    def record(request, handler):
                        prompts.append(request.system_message.content)
                        return handler(request)

                    middleware = [*agent._middleware(), wrap_model_call(record)]
                    with patch.object(agent, "_middleware", return_value=middleware):
                        agent.invoke("hello")
                    self.assertIn("Remember the project marker.", str(prompts))
                    self.assertIn("Example skill marker.", str(prompts))


if __name__ == "__main__":
    unittest.main()
