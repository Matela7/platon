from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

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

    def invoke(self, task: str, *, config: dict[str, Any] | None = None) -> Any:
        return {"messages": [AIMessage(content=f"done: {task}")]}


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
        answer = supervisor.tools_list[2].invoke({"task": "find in RAG"})
        self.assertEqual(answer, "done: find in RAG")

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
        database_agent = cast(DatabaseAgent, supervisor.subagents["database"])
        self.assertIsNone(database_agent.client_manager._client)

    def test_chroma_client_is_lazy(self) -> None:
        manager = ClientManager("unused-in-this-test")
        self.assertIsNone(manager._client)


if __name__ == "__main__":
    unittest.main()
