"""Web research agent, deliberately separated from private RAG data."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from platon.agent.workflow_agent import WorkflowAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.tools.http import create_http_tools
from platon.agent.tools.utilities import create_utils_tools
from platon.agent.tools.web import create_web_search_tools


class ResearchAgent(WorkflowAgent):
    """Research public sources through search and HTTP tools."""

    agent_name = "research_agent"
    prompt_path = "agents/research.md"
    delegation_description = (
        "Delegate public web research, current-information checks, and reading public HTTP/API sources. "
        "Use this specialist when the answer needs fresh or externally verified information. It can search, "
        "open exact result URLs, check the current time, distinguish ambiguous terms, and return source links. "
        "It cannot inspect workspace files or private knowledge-base collections."
    )
    read_only_tools = frozenset({"search_web", "http_get", "get_current_time"})

    def __init__(
        self,
        model: BaseChatModel,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
        max_tool_calls: int | None = None,
    ) -> None:
        if max_tool_calls is None:
            max_tool_calls = (config or AgentConfig()).research_tool_limit
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least 1")
        self.max_tool_calls = max_tool_calls
        super().__init__(
            model=model,
            config=config,
            tools_list=tools_list,
            prompt=prompt,
            checkpointer=checkpointer,
        )
        if tools_list is None:
            time_tools = [
                tool_instance
                for tool_instance in create_utils_tools()
                if tool_instance.name == "get_current_time"
            ]
            tools_list = [
                *create_web_search_tools(),
                *create_http_tools(self.config.max_tool_output_chars),
                *time_tools,
            ]
            self.tools_list = tools_list
