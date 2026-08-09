"""Top-level agent that can act only directly or through delegation."""

from __future__ import annotations

from typing import Any, Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from agent.adapters.delegation import create_delegation_tools
from agent.base_agent import BaseAgent
from agent.prompt_loader import load_prompt

from agent.agents.coding_agent import CodingAgent
from agent.agents.database_agent import DatabaseAgent
from agent.agents.research_agent import ResearchAgent
from agent.models.agent_config import AgentConfig
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig


DELEGATION_DESCRIPTIONS = {
    "research": "Delegate public web research and direct HTTP/API reading.",
    "coding": "Delegate workspace file changes, shell commands, and code execution.",
    "database": "Delegate every private knowledge-base or RAG operation.",
}


class SupervisorAgent(BaseAgent):
    """Coordinate specialized agents without receiving their tools directly."""

    agent_name = "supervisor_agent"
    prompt_path = "react_prompt.md"

    def __init__(
        self,
        model: BaseChatModel,
        subagents: Mapping[str, BaseAgent],
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.subagents = dict(subagents)
        if tools_list is None:
            tools_list = create_delegation_tools(
                self.subagents,
                DELEGATION_DESCRIPTIONS,
            )
        self._reject_direct_rag_tools(tools_list)
        super().__init__(
            model=model,
            config=config,
            tools_list=tools_list,
            prompt=prompt,
            checkpointer=checkpointer,
        )

    @classmethod
    def from_config(
        cls,
        agent_config: AgentConfig,
        runtime_config: AgentOrchestratorConfig,
        *,
        model: BaseChatModel | None = None,
    ) -> SupervisorAgent:
        """Build the supervisor and its specialists from application config."""

        shared_model = model
        if shared_model is None:
            shared_model = ChatOllama(
                model=agent_config.model_name,
                base_url=runtime_config.base_url,
                keep_alive=agent_config.keep_alive,
            )
        subagents: dict[str, BaseAgent] = {
            "research": ResearchAgent(
                model=shared_model,
                config=agent_config,
            ),
            "coding": CodingAgent(
                model=shared_model,
                working_dir=runtime_config.working_dir,
                config=agent_config,
            ),
            "database": DatabaseAgent.from_persist_dir(
                model=shared_model,
                persist_dir=runtime_config.persist_dir,
                config=agent_config,
            ),
        }
        return cls(
            model=shared_model,
            subagents=subagents,
            config=agent_config,
            prompt=load_prompt(agent_config.system_prompt),
        )

    @staticmethod
    def _reject_direct_rag_tools(tools_list: list[BaseTool]) -> None:
        forbidden = {
            "search_collection",
            "search_all_collections",
            "get_list_of_collections",
            "add_document_to_collection",
        }
        exposed = forbidden & {tool_instance.name for tool_instance in tools_list}
        if exposed:
            names = ", ".join(sorted(exposed))
            raise ValueError(f"SupervisorAgent cannot receive direct RAG tools: {names}")
