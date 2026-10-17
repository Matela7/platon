"""One bounded agent loop with approval for mutations and host execution."""

from typing import Any

from langchain.agents.middleware import (
    HumanInTheLoopMiddleware, ModelCallLimitMiddleware, ToolCallLimitMiddleware,
)

from agent.base_agent import BaseAgent


class WorkflowAgent(BaseAgent):
    read_only_tools: frozenset[str] = frozenset()
    max_tool_calls = 6

    def _middleware(self) -> list[Any]:
        return [
            *super()._middleware(),
            ToolCallLimitMiddleware(run_limit=self.max_tool_calls, exit_behavior="continue"),
            ModelCallLimitMiddleware(run_limit=self.max_tool_calls + 2, exit_behavior="end"),
            HumanInTheLoopMiddleware(
                interrupt_on={
                    tool.name: {"allowed_decisions": ["approve", "reject"]}
                    for tool in self.tools_list
                    if tool.name not in self.read_only_tools and tool.name != "ask_user"
                },
                description_prefix=self.agent_name,
            ),
        ]
