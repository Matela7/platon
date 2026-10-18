"""Pass task goals, evidence and failure reports across specialist boundaries."""

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Mapping

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from platon.app_logging import LOGGER, log_call
from platon.agent.base_agent import BaseAgent
from platon.agent.context import bounded_messages
from platon.agent.results import content_text, current_turn, execution_report
from platon.agent.tools.errors import ToolError


def _excerpt(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    marker = f" [truncated; {len(text) - limit} more characters] "
    head = max(0, (limit - len(marker)) * 2 // 3)
    tail = max(0, limit - len(marker) - head)
    return text[:head] + marker + (text[-tail:] if tail else "")


def _compact_report(report: Any) -> dict[str, Any]:
    """Pass useful findings and failure details without replaying raw tool logs."""
    if not isinstance(report, dict):
        return {"answer": _excerpt(report, 2_000)}
    compact = {key: report[key] for key in ("agent", "user_request", "task", "status") if key in report}
    compact["answer"] = _excerpt(report.get("answer", ""), 1_500)
    errors = report.get("errors", [])
    if errors:
        compact["errors"] = [
            {**{key: item[key] for key in ("category", "operation", "tool", "retryable") if key in item},
             "message": _excerpt(item.get("message", ""), 500)}
            if isinstance(item, dict) else {"message": _excerpt(item, 500)}
            for item in errors[:5]
        ]
        if len(errors) > 5:
            compact["omitted_errors"] = len(errors) - 5
    evidence = report.get("evidence", [])
    if isinstance(evidence, list) and evidence:
        snippets = []
        for item in evidence:
            if not isinstance(item, dict):
                snippets.append(_excerpt(item, 400))
                continue
            output = item.get("output")
            if isinstance(output, list) and output and all(isinstance(row, dict) and "document" in row for row in output):
                # A single search tool result can hold 25 passages. Sample *inside*
                # every result group, preserving both books and their page metadata.
                indices = range(min(len(output), 4))
                rows = []
                for index in indices:
                    row = output[index]
                    rows.append({"document_excerpt": _excerpt(row["document"], 650),
                                 "metadata": row.get("metadata"),
                                 **({"distance": row["distance"]} if "distance" in row else {})})
                snippets.append({"tool": item.get("tool"), "status": item.get("status"),
                                 "passages": rows, "omitted_passages": len(output) - len(indices)})
            elif item.get("status") in {"error", "partial"}:
                snippets.append({"tool": item.get("tool"), "status": item.get("status"),
                                 "output": _excerpt(output, 500)})
            elif len(snippets) < 4:
                snippets.append({"tool": item.get("tool"), "status": item.get("status"),
                                 "output": _excerpt(output, 400)})
        compact["evidence"] = snippets[:16]
        if len(snippets) > 16:
            compact["omitted_evidence"] = len(snippets) - 16
    return compact


def _source_files(value: str) -> set[str]:
    return set(re.findall(r"[\w.-]+\.(?:pdf|docx|txt)\b", value.casefold()))


def _same_goal(first: str, second: str) -> bool:
    # Different source documents mean different work, even when nearly every
    # other word in two analysis requests is identical.
    if _source_files(first) != _source_files(second):
        return False

    def words(value: str) -> list[str]:
        return re.findall(r"\w+", value.casefold(), flags=re.UNICODE)
    left, right = words(first), words(second)
    if not left or not right:
        return first.strip() == second.strip()
    overlap = len(set(left) & set(right)) / max(1, min(len(set(left)), len(set(right))))
    return overlap >= .8 and SequenceMatcher(None, " ".join(left), " ".join(right)).ratio() >= .65


def _meaningful_retry(reason: str) -> bool:
    cleaned = " ".join(reason.casefold().split())
    generic = {"retry", "try again", "ponów", "ponow", "spróbuj ponownie", "sprobuj ponownie",
               "krócej", "krocej", "concise", "shorter"}
    return len(cleaned) >= 20 and cleaned not in generic


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
    if not turn or not isinstance(turn[0], HumanMessage):
        raise ToolError(tool_name, "validating delegated request", "No latest user message is available for delegation.")
    # A generated summary can become the active HumanMessage after compaction.
    # It is trusted as context, but must not be mistaken for the user's wording.
    source = (turn[0].additional_kwargs.get("lc_source")
              or turn[0].response_metadata.get("lc_source"))
    if source != "summarization" and user_request not in content_text(turn[0].content):
        LOGGER.warning("Delegated request should be copied from the latest user message without expanding its scope (tool=%s, user_request=%s)", tool_name, user_request)
    prior = messages[:len(messages) - len(turn)]
    context = [m for m in prior if isinstance(m, HumanMessage) or isinstance(m, AIMessage) and not m.tool_calls]
    # Pass reports as task data, avoiding orphan tool responses.
    reports = [
        {"agent_tool": m.name, "report": _compact_report(m.artifact if m.artifact is not None else content_text(m.content))}
        for m in messages if isinstance(m, ToolMessage) and m.name and m.name.startswith("delegate_")
    ][-3:]
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
                role_reports = [m.artifact for m in current_turn(runtime.state.get("messages", []))
                                if isinstance(m, ToolMessage) and m.name == self.tool_name
                                and isinstance(m.artifact, dict)
                                and _same_goal(m.artifact.get("user_request", ""), user_request)]
                requested_files = _source_files(task or user_request)
                completed = [item for item in role_reports if item.get("status") == "completed"
                             and not (_source_files(item.get("task") or item.get("user_request", ""))
                                      and requested_files
                                      and _source_files(item.get("task") or item.get("user_request", ""))
                                      != requested_files)]
                if completed:
                    LOGGER.info("Reusing completed delegated result (role=%s)", self.role)
                    return json.dumps(_compact_report(completed[-1]), ensure_ascii=False), completed[-1]
                previous = [item for item in role_reports
                            if _same_goal(item.get("task") or item.get("user_request", ""), task or user_request)]
                if previous:
                    if len(previous) >= 2 or not _meaningful_retry(retry_reason):
                        raise ToolError(self.tool_name, "retrying delegated task", "A repeated incomplete task needs a concrete changed approach; do not repeat the same failed attempt.")
                    if any(error.get("retryable") is False and error.get("category") in {"permission", "validation"}
                           for error in previous[-1].get("errors", []) if isinstance(error, dict)):
                        raise ToolError(self.tool_name, "retrying delegated task", "The previous failure is not retryable without correcting its inputs or permissions.")
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
        return json.dumps(_compact_report(report), ensure_ascii=False), report

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
