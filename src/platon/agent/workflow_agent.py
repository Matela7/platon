"""One bounded agent loop with approval for mutations and host execution."""

from typing import Any

from langchain.agents.middleware import (
    HumanInTheLoopMiddleware, ModelCallLimitMiddleware, ToolCallLimitMiddleware,
)
from deepagents.middleware import UnsupportedContentMiddleware

from platon.agent.base_agent import BaseAgent
from platon.agent.shared_middleware import shared_filesystem_middleware


class WorkflowAgent(BaseAgent):
    read_only_tools: frozenset[str] = frozenset()
    max_tool_calls = 6
    use_shared_filesystem = True

    def _middleware(self) -> list[Any]:
        return [
            *([shared_filesystem_middleware(self.config.backend_root)]
              if self.use_shared_filesystem else []),
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
            UnsupportedContentMiddleware(),
        ]
