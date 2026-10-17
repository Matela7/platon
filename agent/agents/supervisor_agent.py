"""Deep-agent supervisor coordinating specialists and human clarification."""

from __future__ import annotations

from typing import Any, Mapping

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from agent.adapters.delegation import create_delegation_tools
from agent.base_agent import BaseAgent
from agent.deep_agent import DeepAgent
from agent.prompt_loader import load_prompt
from agent.tools.tools import ask_user

from agent.agents.coding_agent import CodingAgent
from agent.agents.database_agent import DatabaseAgent
from agent.agents.research_agent import ResearchAgent
from agent.models.agent_config import AgentConfig
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig


class SupervisorAgent(DeepAgent):
    """Coordinate specialists with DeepAgent skills, memory and human input."""

    agent_name = "supervisor_agent"

    def _middleware(self) -> list[Any]:
        """Bound distinct tasks and targeted recovery; reuse identical completed results."""
        delegation_names = [
            tool_instance.name
            for tool_instance in self.tools_list
            if tool_instance.name.startswith("delegate_")
        ]
        return [
            *super()._middleware(),
            *(
                ToolCallLimitMiddleware(
                    tool_name=tool_name,
                    run_limit=3,
                    exit_behavior="continue",
                )
                for tool_name in delegation_names
            ),
            ModelCallLimitMiddleware(
                run_limit=max(4, 3 * len(delegation_names) + 2),
                exit_behavior="end",
            ),
        ]

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
            tools_list = create_delegation_tools(self.subagents)
        tools_list = list(tools_list)
        if not any(tool.name == ask_user.name for tool in tools_list):
            tools_list.append(ask_user)
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
        checkpointer: Any | None = None,
    ) -> SupervisorAgent:
        """Build the supervisor and its specialists from application config."""

        shared_model = model
        if shared_model is None:
            shared_model = ChatOllama(
                model=agent_config.model_name,
                base_url=runtime_config.base_url,
                keep_alive=agent_config.keep_alive,
                num_ctx=agent_config.num_ctx,
                reasoning=agent_config.reasoning,
                temperature=0,
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
            checkpointer=checkpointer,
        )
