"""Tool adapters for delegating a bounded task to a concrete agent."""

from dataclasses import dataclass
from typing import Any, Mapping

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from agent.base_agent import BaseAgent
from agent.tools.errors import ToolError


class DelegationRequest(BaseModel):
    """Exact user request passed across the delegation boundary."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    user_request: str = Field(
        ...,
        min_length=1,
        description=(
            "Paste the relevant text from the latest user message verbatim. If the "
            "whole message belongs to this tool, copy it character-for-character. "
            "Do not summarize, translate, answer, expand, resolve identities, turn "
            "questions into statements, or add facts, people, titles, dates, time "
            "periods, categories, constraints, or inferred scope."
        ),
    )
    runtime: SkipJsonSchema[ToolRuntime] = None  # type: ignore[assignment]


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
            if message.tool_calls:
                continue
            answer = _content_to_text(message.content)
        elif isinstance(message, dict) and message.get("role") == "assistant":
            additional_kwargs = message.get("additional_kwargs")
            has_nested_tool_calls = isinstance(
                additional_kwargs, dict
            ) and bool(additional_kwargs.get("tool_calls"))
            if message.get("tool_calls") or has_nested_tool_calls:
                continue
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


def _conversation_context(
    runtime: ToolRuntime | None,
    user_request: str,
    tool_name: str,
) -> list[BaseMessage]:
    """Return prior user-visible turns and validate the delegated text."""
    if runtime is None:
        return []

    state = runtime.state
    raw_messages = (
        state.get("messages", [])
        if isinstance(state, Mapping)
        else getattr(state, "messages", [])
    )
    messages: list[BaseMessage] = []
    for message in raw_messages:
        if isinstance(message, HumanMessage):
            messages.append(message)
        elif isinstance(message, AIMessage):
            if not message.tool_calls and _content_to_text(message.content):
                messages.append(message)
        elif isinstance(message, dict):
            content = _content_to_text(message.get("content"))
            if not content:
                continue
            if message.get("role") == "user":
                messages.append(HumanMessage(content=content))
            elif message.get("role") == "assistant" and not message.get("tool_calls"):
                messages.append(AIMessage(content=content))

    latest_user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if latest_user_index is None:
        raise ToolError(
            tool_name,
            "validating delegated request",
            "The supervisor state does not contain a user message.",
        )

    latest_user_text = _content_to_text(messages[latest_user_index].content)
    if not latest_user_text or user_request not in latest_user_text:
        raise ToolError(
            tool_name,
            "validating delegated request",
            (
                "user_request must be copied character-for-character from the "
                "latest user message; paraphrases and expanded scope are rejected."
            ),
        )

    # The concrete delegated text becomes the specialist's newest user message.
    # Earlier visible turns remain available for references such as "sprawdź to".
    return messages[:latest_user_index]


@dataclass(frozen=True)
class AgentToolAdapter:
    """Adapt an agent to a LangChain tool without becoming an agent itself."""

    role: str
    agent: BaseAgent
    description: str

    @property
    def tool_name(self) -> str:
        return f"delegate_{self.role}"

    def invoke(
        self,
        user_request: str,
        runtime: ToolRuntime = None,  # type: ignore[assignment]
    ) -> str:
        """Delegate the user's bounded request and normalize the final answer."""
        try:
            context_messages = _conversation_context(
                runtime,
                user_request,
                self.tool_name,
            )
            result = self.agent.invoke(
                user_request,
                context_messages=context_messages,
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
            args_schema=DelegationRequest,
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
