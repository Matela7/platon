"""Pass task goals, evidence and failure reports across specialist boundaries."""

import json
from dataclasses import dataclass
from typing import Any, Mapping

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from app_logging import LOGGER, log_call
from agent.base_agent import BaseAgent
from agent.context import bounded_messages
from agent.results import content_text, current_turn, execution_report
from agent.tools.errors import ToolError


class DelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    user_request: str = Field(min_length=1, description="Relevant original text copied from the latest user message; preserve scope and uncertainty.")
    task: str = Field(default="", description="Concrete goal for this specialist, consistent with the user's request. Dependencies and previous reports are supplied automatically.")
    retry_reason: str = Field(default="", description="For a repeated failed task, explain what changed and why another attempt is useful. Never retry an uncertain mutation blindly.")
    runtime: SkipJsonSchema[ToolRuntime] = None  # type: ignore[assignment]


def _conversation_context(runtime, user_request: str, tool_name: str, limit: int):
    if runtime is None:
        return [], []
    messages = bounded_messages(runtime.state.get("messages", []), limit)
    turn = current_turn(messages)
    if not turn or not isinstance(turn[0], HumanMessage) or user_request not in content_text(turn[0].content):
        # raise ToolError(tool_name, "validating delegated request", "user_request must be copied from the latest user message without expanding its scope.")
        LOGGER.warning("Delegated request should have the user request copied from the latest user message (tool=%s, user_request=%s)", tool_name, user_request)
    prior = messages[:len(messages) - len(turn)]
    context = [m for m in prior if isinstance(m, HumanMessage) or isinstance(m, AIMessage) and not m.tool_calls]
    # Pass reports as task data, avoiding orphan tool responses.
    reports = [
        {"agent_tool": m.name, "report": m.artifact if m.artifact is not None else content_text(m.content)}
        for m in messages if isinstance(m, ToolMessage) and m.name and m.name.startswith("delegate_")
    ]
    return context, reports


@dataclass(frozen=True)
class AgentToolAdapter:
    role: str
    agent: BaseAgent
    description: str

    @property
    def tool_name(self) -> str:
        return f"delegate_{self.role}"

    @log_call
    def invoke(self, user_request: str, task: str = "", retry_reason: str = "", runtime: ToolRuntime = None) -> tuple[str, dict[str, Any]]:
        report = {}
        LOGGER.info("Delegated task started (role=%s)", self.role)
        try:
            context, reports = _conversation_context(runtime, user_request, self.tool_name, self.agent.config.max_history_messages)
            if runtime is not None:
                previous = [m.artifact for m in current_turn(runtime.state.get("messages", []))
                            if isinstance(m, ToolMessage) and m.name == self.tool_name and isinstance(m.artifact, dict)
                            and m.artifact.get("user_request") == user_request and m.artifact.get("task") == task]
                if previous:
                    if previous[-1]["status"] == "completed":
                        LOGGER.info("Reusing completed delegated task (role=%s)", self.role)
                        return json.dumps(previous[-1], ensure_ascii=False), previous[-1]
                    if not retry_reason.strip():
                        raise ToolError(self.tool_name, "retrying delegated task", "Provide a concrete retry_reason and use the previous report before repeating incomplete work.")
            original_request = content_text(current_turn(runtime.state["messages"])[0].content) if runtime else user_request
            # Keep dependencies in the active task so model-context trimming cannot discard them.
            assignment = json.dumps({"user_request": user_request, "original_request": original_request,
                                     "task": task or user_request, "retry_reason": retry_reason,
                                     "dependency_evidence": reports}, ensure_ascii=False)
            result = self.agent.invoke(assignment, context_messages=context, config={
                "run_name": self.agent.agent_name, "max_concurrency": 1,
                "metadata": {"agent": self.agent.agent_name, "tool": self.tool_name},
            })
            report = execution_report(result.get("messages", []))
        except GraphBubbleUp:
            raise
        except Exception as exc:
            LOGGER.error("Delegated task failed (role=%s, exception=%s)", self.role, type(exc).__name__)
            report = execution_report(getattr(exc, "agent_messages", []), error=exc)
        report.update({"agent": self.role, "user_request": user_request, "task": task})
        LOGGER.info("Delegated task finished (role=%s, status=%s)", self.role, report.get("status", "unknown"))
        return json.dumps(report, ensure_ascii=False), report

    def as_tool(self) -> BaseTool:
        def validation_report(exc):
            return json.dumps({"status": "error", "errors": [{"category": "validation", "tool": self.tool_name,
                "message": str(exc), "retryable": False}],
                "recovery": "Correct your tool arguments and call this tool again to complete the user's task. "
                            "Use only user_request (required, exact text from the latest user message), "
                            "task (goal resolved using conversation context), and optional retry_reason. "
                            "Do not pass query, language, locale or runtime. Do not ask the user to fix your tool call."}, ensure_ascii=False)
        return StructuredTool.from_function(
            func=self.invoke, name=self.tool_name,
            description=(
                self.description
                + "\n\nInvocation: pass user_request (required, an exact non-empty excerpt from the latest user "
                  "message), task (the complete specialist goal resolved from conversation context), and "
                  "retry_reason only when retrying incomplete work with a changed approach. Do not pass query, "
                  "language, locale, input, messages, or runtime. Earlier specialist reports are attached "
                  "automatically. The result contains status, answer, evidence, and errors; use it to finish the "
                  "user's request. Run dependent delegations sequentially."
            ),
            args_schema=DelegationRequest, response_format="content_and_artifact",
            handle_validation_error=validation_report,
        )


def create_delegation_tools(
    agents: Mapping[str, BaseAgent],
    descriptions: Mapping[str, str] | None = None,
) -> list[BaseTool]:
    """Expose agents as tools, using descriptions owned by each agent by default."""
    if descriptions is None:
        descriptions = {
            role: agent.delegation_description for role, agent in agents.items()
        }
    missing = agents.keys() - descriptions.keys()
    if missing:
        raise ValueError(f"Missing delegation descriptions for: {', '.join(sorted(missing))}")
    LOGGER.info("Creating specialist delegation tools (count=%d)", len(agents))
    return [AgentToolAdapter(role, agent, descriptions[role]).as_tool() for role, agent in agents.items()]
