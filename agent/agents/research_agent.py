"""Web research agent, deliberately separated from private RAG data."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)
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

    @property
    def max_tool_calls(self) -> int:
        """Maximum tool calls available during one bounded research pass."""
        return self._max_tool_calls

    def _middleware(self) -> list[Any]:
        """Apply the ResearchAgent-owned tool-call ceiling."""
        return [
            ToolCallLimitMiddleware(
                run_limit=self.max_tool_calls,
                exit_behavior="continue",
            ),
            ModelCallLimitMiddleware(
                run_limit=self.max_tool_calls + 1,
                exit_behavior="end",
            ),
        ]

    def _with_tool_budget(self, system_prompt: str) -> str:
        return (
            f"{system_prompt}\n\n"
            "## Active research budget\n\n"
            f"- You may make at most {self.max_tool_calls} total tool calls in "
            "this pass.\n"
            "- The limit is a ceiling, not a target. Stop earlier as soon as you "
            "can give a supported answer.\n"
            "- Do not announce another search or tool call. Either make it now "
            "within the budget or return the answer."
        )

    def _default_prompt(self) -> str:
        return self._with_tool_budget(super()._default_prompt())

    def __init__(
        self,
        model: BaseChatModel,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
        max_tool_calls: int = 3,
    ) -> None:
        if max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least 1")
        self._max_tool_calls = max_tool_calls
        super().__init__(
            model=model,
            config=config,
            tools_list=tools_list,
            prompt=prompt,
            checkpointer=checkpointer,
        )
        if self.prompt is not None:
            self.prompt = self._with_tool_budget(self.prompt)
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
