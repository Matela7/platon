"""Check graph reuse, streaming and DeepAgent's local context and interrupts."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from platon.agent.base_agent import BaseAgent
from platon.agent.deep_agent import DeepAgent
from platon.agent.agents.supervisor_agent import SupervisorAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class AgentRuntimeTests(unittest.TestCase):
    def test_ollama_retries_checkpoint_with_pdf_without_sending_file_blocks(self):
        """Exercise real Ollama serialization on a failed graph and its restarted run."""
        def serialize_and_respond(model, messages, *args, **kwargs):
            model._convert_messages_to_ollama_messages(messages)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

        with TemporaryDirectory() as directory:
            root = Path(directory)
            agent_config = AgentConfig(backend_root=root, skills=[], memory=[])
            runtime_config = AgentOrchestratorConfig(working_dir=root)
            checkpointer = InMemorySaver()
            run_config = {"configurable": {"thread_id": "pdf-retry"}}
            pdf = {"type": "file", "base64": "JVBERi0xLjQK", "mime_type": "application/pdf"}
            messages = [
                HumanMessage(content="Analyze the local document"),
                AIMessage(content="", tool_calls=[{
                    "name": "read_file", "args": {"file_path": "/documents/example.pdf"},
                    "id": "read-pdf", "type": "tool_call",
                }]),
                ToolMessage(content=[pdf], tool_call_id="read-pdf", name="read_file",
                            additional_kwargs={"read_file_path": "/documents/example.pdf"}),
            ]
            with patch.object(ChatOllama, "_generate", serialize_and_respond):
                # Reproduce the previous configuration and leave the failing node checkpointed.
                previous = SupervisorAgent.from_config(
                    agent_config, runtime_config, checkpointer=checkpointer,
                )
                previous.model.profile = None
                with self.assertRaisesRegex(ValueError, "Blocks of type file not supported"):
                    previous.runnable.invoke({"messages": messages}, run_config)

                restarted = SupervisorAgent.from_config(
                    agent_config, runtime_config, checkpointer=checkpointer,
                )
                result = restarted.runnable.invoke(None, run_config)
                self.assertEqual(result["messages"][-1].content, "done")
                # Filtering affects the model request, preserving the original checkpoint content.
                attachment = next(m for m in result["messages"] if isinstance(m, ToolMessage))
                self.assertEqual(attachment.content[0]["type"], "file")
                self.assertFalse(restarted.runnable.get_state(run_config).next)

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

    def test_fresh_backend_creates_defaults_and_preserves_memory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "new-backend"
            config = AgentConfig(backend_root=root)
            for _ in range(2):
                agent = DeepAgent(ScriptedModel(responses=[AIMessage(content="ok")]),
                                  config=config, prompt="test")
                agent.create_agent()
                self.assertTrue((root / "skills").is_dir())
                memory = root / "memory/AGENTS.md"
                self.assertTrue(memory.is_file())
                if _ == 0:
                    memory.write_text("Keep my memory", encoding="utf-8")
            self.assertEqual(memory.read_text(encoding="utf-8"), "Keep my memory")

    def test_disabled_sources_do_not_create_default_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            agent = DeepAgent(ScriptedModel(responses=[AIMessage(content="ok")]),
                              config=AgentConfig(backend_root=root, skills=[], memory=[]),
                              prompt="test")
            agent.create_agent()
            self.assertFalse((root / "skills").exists())
            self.assertFalse((root / "memory").exists())

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
            for agent_type in (DeepAgent, SupervisorAgent):
                with self.subTest(agent=agent_type.__name__):
                    options = {"subagents": {}} if agent_type is SupervisorAgent else {}
                    agent = agent_type(
                        ScriptedModel(responses=[AIMessage(content="ok")]),
                        config=AgentConfig(backend_root=root), prompt="test", **options,
                    )
                    with patch.object(
                        ScriptedModel, "_generate", autospec=True,
                        side_effect=ScriptedModel._generate,
                    ) as generate:
                        agent.invoke("hello")
                    prompts = generate.call_args.args[1]
                    self.assertIn("Remember the project marker.", str(prompts))
                    self.assertIn("Example skill marker.", str(prompts))


if __name__ == "__main__":
    unittest.main()
