"""Deep-agent supervisor coordinating specialists and human clarification."""

from __future__ import annotations

from pathlib import Path

from typing import Any, Mapping

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.messages import ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_ollama import ChatOllama

from platon.agent.adapters.delegation import create_delegation_tools
from platon.agent.base_agent import BaseAgent
from platon.agent.deep_agent import DeepAgent
from platon.agent.prompt_loader import load_prompt
from platon.agent.tools.interaction import ask_user

from platon.agent.agents.coding_agent import CodingAgent
from platon.agent.agents.gmail_agent import GmailAgent
from platon.agent.agents.database_agent import DatabaseAgent
from platon.agent.agents.research_agent import ResearchAgent
from platon.agent.agents.skill_creator_agent import SkillCreatorAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig


class DocumentReadGuard(AgentMiddleware):
    """Keep document contents on the database/RAG route."""

    @staticmethod
    def _blocked(request: Any) -> bool:
        if request.tool_call.get("name") != "read_file":
            return False
        path = request.tool_call.get("args", {}).get("file_path", "")
        if not isinstance(path, str):
            return False
        normalized = path.replace("\\", "/").lower()
        return (
            normalized.endswith(".pdf")
            or normalized == "/documents"
            or normalized.startswith("/documents/")
        )

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        if self._blocked(request):
            return ToolMessage(
                content="Document content must be retrieved through delegate_database and RAG.",
                tool_call_id=request.tool_call["id"],
                name="read_file",
                status="error",
            )
        return handler(request)


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
            DocumentReadGuard(),
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
        *,
        subagent_model: BaseChatModel | None = None,
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
            subagent_model=subagent_model,
        )

    @classmethod
    def from_config(
        cls,
        agent_config: AgentConfig,
        runtime_config: AgentOrchestratorConfig,
        *,
        model: BaseChatModel | None = None,
        subagent_model: BaseChatModel | None = None,
        checkpointer: Any | None = None,
    ) -> SupervisorAgent:
        """Use the optional subagent model, otherwise share the supervisor model."""

        shared_model = model
        if shared_model is None:
            shared_model = ChatOllama(
                model=agent_config.model_name,
                temperature=agent_config.model_temperature,
                base_url=runtime_config.base_url,
                keep_alive=agent_config.keep_alive,
                num_ctx=agent_config.num_ctx,
                reasoning=agent_config.reasoning,
                # ChatOllama cannot serialize PDF blocks; let middleware replace them.
                profile={"pdf_inputs": False, "pdf_tool_message": False},
            )
        specialist_model = subagent_model if subagent_model is not None else shared_model
        subagents: dict[str, BaseAgent] = {
            "research": ResearchAgent(
                model=specialist_model,
                config=agent_config,
            ),
            "coding": CodingAgent(
                model=specialist_model,
                working_dir=runtime_config.working_dir,
                config=agent_config,
            ),
            "database": DatabaseAgent.from_persist_dir(
                model=specialist_model,
                persist_dir=runtime_config.persist_dir,
                config=agent_config,
            ),
            "skill_creator": SkillCreatorAgent(model=specialist_model, config=agent_config),
            "gmail": GmailAgent(model=specialist_model, config=agent_config,
                                config_path=Path.cwd() / ".mcp.json"),
        }
        return cls(
            model=shared_model,
            subagents=subagents,
            config=agent_config,
            prompt=load_prompt(agent_config.system_prompt),
            checkpointer=checkpointer,
            subagent_model=subagent_model,
        )

    def close(self):
        for agent in self.subagents.values():
            close = getattr(agent, "close", None)
            if close is not None:
                close()
