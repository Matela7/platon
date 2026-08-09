"""Tool adapters for delegating a bounded task to a concrete agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, StructuredTool

from agent.base_agent import BaseAgent
from agent.tools.errors import ToolError


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(part.strip() for part in parts if part.strip()).strip()


def _extract_agent_answer(result: Any, agent_name: str) -> str:
    if not isinstance(result, dict):
        raise ToolError(
            agent_name,
            "reading delegated result",
            f"Expected a result dictionary, received {type(result).__name__}.",
        )

    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage):
            answer = _content_to_text(message.content)
        elif isinstance(message, dict) and message.get("role") == "assistant":
            answer = _content_to_text(message.get("content"))
        else:
            continue
        if answer:
            return answer

    raise ToolError(
        agent_name,
        "reading delegated result",
        "The delegated agent completed without a final assistant message.",
    )


@dataclass(frozen=True)
class AgentToolAdapter:
    """Adapt an agent to a LangChain tool without becoming an agent itself."""

    role: str
    agent: BaseAgent
    description: str

    @property
    def tool_name(self) -> str:
        return f"delegate_{self.role}"

    def invoke(self, task: str) -> str:
        """Delegate one task and normalize the agent's final answer."""
        try:
            result = self.agent.invoke(
                task,
                config={
                    "run_name": self.agent.agent_name,
                    "tags": ["platon", "delegated-agent", self.role],
                    "metadata": {
                        "agent": self.agent.agent_name,
                        "tool": self.tool_name,
                    },
                },
            )
            return _extract_agent_answer(result, self.agent.agent_name)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError.from_exception(
                self.tool_name,
                f"delegating task to {self.agent.agent_name}",
                exc,
            ) from exc

    def as_tool(self) -> BaseTool:
        """Build the LangChain tool exposed to the supervisor."""
        return StructuredTool.from_function(
            func=self.invoke,
            name=self.tool_name,
            description=self.description,
            handle_tool_error=True,
            handle_validation_error=(
                lambda exc: f"Tool '{self.tool_name}' received invalid arguments: {exc}"
            ),
        )


def create_delegation_tools(
    agents: Mapping[str, BaseAgent],
    descriptions: Mapping[str, str],
) -> list[BaseTool]:
    """Expose concrete agents as ordered delegation tools."""
    missing_descriptions = agents.keys() - descriptions.keys()
    if missing_descriptions:
        missing = ", ".join(sorted(missing_descriptions))
        raise ValueError(f"Missing delegation descriptions for: {missing}")
    return [
        AgentToolAdapter(role, agent, descriptions[role]).as_tool()
        for role, agent in agents.items()
    ]
