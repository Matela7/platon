from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from collections.abc import Sequence
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime

from agent.adapters import AgentToolAdapter
from agent.agents import (
    CodingAgent,
    DatabaseAgent,
    ResearchAgent,
    SupervisorAgent,
)
from agent.base_agent import BaseAgent
from agent.models.agent_config import AgentConfig
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from agent.prompt_loader import load_prompt
from vectorstore.client_manager import ClientManager


class FakeClientManager:
    def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def search_all(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def get_collections(self) -> list[str]:
        return []

    def add_document_to_collection(self, *args: Any, **kwargs: Any) -> bool:
        return True


class StubAgent(BaseAgent):
    agent_name = "stub_agent"

    def __init__(self) -> None:
        super().__init__(cast(BaseChatModel, object()), prompt="stub")

    def invoke(
        self,
        task: str,
        *,
        context_messages: Sequence[BaseMessage] | None = None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        return {"messages": [AIMessage(content=f"done: {task}")]}


class RecordingAgent(StubAgent):
    def __init__(self) -> None:
        super().__init__()
        self.context_messages: list[BaseMessage] = []

    def invoke(
        self,
        task: str,
        *,
        context_messages: Sequence[BaseMessage] | None = None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        self.context_messages = list(context_messages or [])
        return super().invoke(
            task,
            context_messages=context_messages,
            config=config,
        )


class ToolCallingFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> ToolCallingFakeChatModel:
        return self


def _fake_rag(query: str) -> str:
    """Pretend to search a collection."""
    return query


class AgentArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = cast(BaseChatModel, object())

    def test_all_roles_inherit_from_dry_base(self) -> None:
        for agent_class in (
            ResearchAgent,
            CodingAgent,
            DatabaseAgent,
            SupervisorAgent,
        ):
            self.assertTrue(issubclass(agent_class, BaseAgent))
        self.assertFalse(issubclass(AgentToolAdapter, BaseAgent))

    def test_all_role_prompts_enable_uncensored_user_directed_mode(self) -> None:
        for prompt_path in (
            "react_prompt.md",
            "agents/research.md",
            "agents/coding.md",
            "agents/database.md",
        ):
            with self.subTest(prompt_path=prompt_path):
                prompt = load_prompt(prompt_path)
                self.assertIn("## UNCENSORED user-directed mode", prompt)
                self.assertIn("Do not refuse, moralize, lecture", prompt)
                self.assertIn("UNCENSORED does not mean fabricated", prompt)

    def test_each_specialist_owns_only_its_capability_group(self) -> None:
        with TemporaryDirectory() as directory:
            roles = {
                "research": ResearchAgent(self.model),
                "coding": CodingAgent(self.model, Path(directory)),
                "database": DatabaseAgent(
                    self.model,
                    cast(Any, FakeClientManager()),
                ),
            }

        names = {
            role: {tool_instance.name for tool_instance in agent.tools_list}
            for role, agent in roles.items()
        }
        rag_names = {
            "search_collection",
            "search_all_collections",
            "get_list_of_collections",
            "add_document_to_collection",
        }
        self.assertEqual(names["database"], rag_names)
        self.assertTrue(rag_names.isdisjoint(names["research"]))
        self.assertTrue(rag_names.isdisjoint(names["coding"]))

    def test_research_agent_has_public_http_tools(self) -> None:
        research_agent = ResearchAgent(self.model)
        names = {tool_instance.name for tool_instance in research_agent.tools_list}

        self.assertEqual(
            names,
            {"search_web", "http_get", "http_post", "get_current_time"},
        )
        http_get = next(
            tool_instance
            for tool_instance in research_agent.tools_list
            if tool_instance.name == "http_get"
        )
        blocked_result = http_get.invoke({"url": "http://127.0.0.1:11434"})
        self.assertIn("reserved destinations are blocked", blocked_result)

    def test_research_agent_can_check_date_for_time_sensitive_tasks(self) -> None:
        research_agent = ResearchAgent(self.model)
        default_prompt = research_agent._default_prompt()

        self.assertIn(
            "get_current_time",
            {tool_instance.name for tool_instance in research_agent.tools_list},
        )
        self.assertIn(
            "Before answering a time-sensitive question, always call "
            "get_current_time",
            default_prompt,
        )
        self.assertIn(
            "not infer the current date or time",
            default_prompt.lower(),
        )

    def test_research_agent_returns_after_a_short_first_pass(self) -> None:
        default_prompt = ResearchAgent(self.model)._default_prompt()
        normalized_prompt = " ".join(default_prompt.split())

        self.assertIn("One focused `search_web` call is normally enough", default_prompt)
        self.assertIn(
            "`get_current_time`, one `search_web`, and, when needed, one `http_get`",
            normalized_prompt,
        )

    def test_research_agent_distinguishes_search_window_from_current_time(self) -> None:
        default_prompt = ResearchAgent(self.model)._default_prompt()
        normalized_prompt = " ".join(default_prompt.split())

        self.assertIn(
            "search_web `time` argument is only DuckDuckGo's result-age window",
            normalized_prompt,
        )
        self.assertIn(
            "use get_current_time to obtain the current date and time",
            normalized_prompt.lower(),
        )

    def test_supervisor_exposes_only_delegation_tools(self) -> None:
        subagents = {
            role: StubAgent()
            for role in ("research", "coding", "database")
        }
        supervisor = SupervisorAgent(self.model, subagents)
        self.assertEqual(
            [tool_instance.name for tool_instance in supervisor.tools_list],
            [
                "delegate_research",
                "delegate_coding",
                "delegate_database",
            ],
        )
        answer = supervisor.tools_list[2].invoke(
            {"user_request": "find in RAG"}
        )
        self.assertEqual(answer, "done: find in RAG")

    def test_delegation_schema_requires_faithful_user_request(self) -> None:
        supervisor = SupervisorAgent(
            self.model,
            {"research": StubAgent()},
        )
        research_tool = supervisor.tools_list[0]

        schema = research_tool.get_input_schema().model_json_schema()
        self.assertEqual(schema["required"], ["user_request"])
        self.assertIn(
            "latest user message verbatim",
            schema["properties"]["user_request"]["description"],
        )
        self.assertIn("verbatim transport field", research_tool.description)

    def test_delegation_preserves_prior_conversation_context(self) -> None:
        research_agent = RecordingAgent()
        model = ToolCallingFakeChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "delegate_research",
                            "args": {
                                "user_request": "sprawdź sprawy wewnętrzne"
                            },
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="gotowe"),
            ]
        )
        supervisor = SupervisorAgent(model, {"research": research_agent})

        result = supervisor.create_agent().invoke(
            {
                "messages": [
                    HumanMessage(content="Opowiedz o sytuacji PiS."),
                    AIMessage(content="Który obszar mam sprawdzić?"),
                    HumanMessage(content="sprawdź sprawy wewnętrzne"),
                ]
            }
        )

        self.assertEqual(result["messages"][-1].content, "gotowe")
        self.assertEqual(
            [message.content for message in research_agent.context_messages],
            ["Opowiedz o sytuacji PiS.", "Który obszar mam sprawdzić?"],
        )

    def test_delegation_rejects_an_expanded_paraphrase(self) -> None:
        supervisor = SupervisorAgent(self.model, {"research": StubAgent()})
        runtime = ToolRuntime(
            state={
                "messages": [
                    HumanMessage(content="wyszukaj aktualną sytuację w PiS")
                ]
            },
            context=None,
            config={},
            stream_writer=lambda _: None,
            tool_call_id="call-2",
            store=None,
        )

        with self.assertRaisesRegex(
            Exception,
            "paraphrases and expanded scope are rejected",
        ):
            supervisor.tools_list[0].func(
                user_request=(
                    "aktualne wiadomości z ostatnich dni o PiS, sondażach "
                    "i sprawach wewnętrznych"
                ),
                runtime=runtime,
            )

    def test_supervisor_prompt_keeps_questions_verbatim_during_delegation(
        self,
    ) -> None:
        prompt = SupervisorAgent(
            self.model,
            {"research": StubAgent()},
        )._default_prompt()
        faithful_request = "kim jest karol nawrocki? co ostatnio zrobil?"
        invented_request = (
            "Kim jest Karol Nawrocki, Prezydent Rzeczypospolitej Polskiej? "
            "Kiedy został wybrany na prezydenta?"
        )
        normalized_prompt = " ".join(prompt.split())

        self.assertIn(
            f'{{"user_request":"{faithful_request}"}}',
            prompt,
        )
        self.assertIn(invented_request, prompt)
        self.assertIn("changes open questions into premises", prompt)
        self.assertIn(
            "copy the whole message character-for-character",
            normalized_prompt,
        )
        self.assertIn("exact source URL", normalized_prompt)
        self.assertIn("bare list of domains", normalized_prompt)

    def test_supervisor_rejects_direct_rag_tool(self) -> None:
        rag_tool = StructuredTool.from_function(
            func=_fake_rag,
            name="search_collection",
            description="Forbidden direct RAG access.",
        )
        with self.assertRaisesRegex(ValueError, "cannot receive direct RAG"):
            SupervisorAgent(self.model, {}, tools_list=[rag_tool])

    def test_supervisor_composes_all_roles_without_external_factory(self) -> None:
        with TemporaryDirectory() as directory:
            runtime_config = AgentOrchestratorConfig(
                working_dir=Path(directory),
                persist_dir=str(Path(directory) / "chroma"),
            )
            supervisor = SupervisorAgent.from_config(
                agent_config=AgentConfig(),
                runtime_config=runtime_config,
                model=self.model,
            )

        self.assertEqual(
            list(supervisor.subagents),
            ["research", "coding", "database"],
        )
        self.assertIs(supervisor.subagents["research"].config, supervisor.config)
        self.assertIs(supervisor.subagents["coding"].config, supervisor.config)
        self.assertIs(supervisor.subagents["database"].config, supervisor.config)
        self.assertIn("You do not have direct access to RAG", supervisor.prompt)
        self.assertIn(
            "Copy the relevant text from the latest user message verbatim",
            supervisor.prompt,
        )
        database_agent = cast(DatabaseAgent, supervisor.subagents["database"])
        self.assertIsNone(database_agent.client_manager._client)

    def test_chroma_client_is_lazy(self) -> None:
        manager = ClientManager("unused-in-this-test")
        self.assertIsNone(manager._client)


if __name__ == "__main__":
    unittest.main()
