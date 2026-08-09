"""Web research agent, deliberately separated from private RAG data."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.base_agent import BaseAgent
from agent.models.agent_config import AgentConfig
from agent.tools.tools import (
    create_http_tools,
    create_utils_tools,
    create_web_search_tools,
)


class ResearchAgent(BaseAgent):
    """Research public sources through search and HTTP tools."""

    agent_name = "research_agent"
    prompt_path = "agents/research.md"

    def __init__(
        self,
        model: BaseChatModel,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
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
