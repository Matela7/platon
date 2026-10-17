"""Small, factual reports shared by delegation, persistence and the UI."""

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from agent.tools.errors import error_details


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            text for item in content
            if (text := content_text(item.get("text") if isinstance(item, dict) else item))
        )
    return ""


def current_turn(messages: list[BaseMessage]) -> list[BaseMessage]:
    start = next((i for i in range(len(messages) - 1, -1, -1)
                  if isinstance(messages[i], HumanMessage)), 0)
    return messages[start:]


def final_answer(messages: list[BaseMessage]) -> str:
    """Only the last message of this turn can be a final answer."""
    turn = current_turn(messages)
    if turn and isinstance(turn[-1], AIMessage) and not turn[-1].tool_calls:
        return content_text(turn[-1].content)
    return ""


def execution_report(messages: list[BaseMessage], error: Exception | None = None) -> dict[str, Any]:
    turn = current_turn(messages)
    evidence = []
    errors = []
    for index, message in enumerate(turn):
        if not isinstance(message, ToolMessage):
            continue
        output = message.artifact if message.artifact is not None else content_text(message.content)
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except (ValueError, TypeError):
                pass
        status = output.get("status", message.status) if isinstance(output, dict) else message.status
        evidence.append({"tool": message.name, "status": status, "output": output})
        if message.status == "error":
            tool_errors = ((output.get("errors", []) if isinstance(output, dict) else [])
                           or [{"message": content_text(message.content)}])
            # Invalid arguments execute nothing. A corrected, successful call resolves them;
            # preserve the failed call in evidence without reporting a failed final task.
            recovered_validation = all(isinstance(item, dict) and item.get("category") == "validation" for item in tool_errors) and any(
                isinstance(later, ToolMessage) and later.name == message.name and later.status != "error"
                and (not isinstance(later.artifact, dict) or later.artifact.get("status") not in {"error", "partial"})
                for later in turn[index + 1:]
            )
            if not recovered_validation:
                errors.extend(tool_errors)
        elif isinstance(output, dict) and output.get("status") in {"partial", "error"}:
            errors.extend(output.get("errors", []) or [{"message": "Delegated work is incomplete."}])
    if error is not None:
        errors.append(error_details(error))
    answer = final_answer(messages) if error is None else ""
    if answer.startswith("Model call limits exceeded:"):
        errors.append({"category": "limit", "message": answer, "retryable": False})
        answer = ""
    if not answer and not errors:
        errors.append({"category": "incomplete", "message": "No final answer was produced.", "retryable": False})
    progress = bool(answer) or any(item["status"] != "error" for item in evidence)
    progress = progress or any(item.get("partial_results") for item in errors)
    return {
        "status": "partial" if errors and progress else "error" if errors else "completed",
        "answer": answer,
        "evidence": evidence,
        "errors": errors,
    }


def visible_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Keep user turns and terminal answers, excluding tool plans and intermediate text."""
    visible = []
    for i, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            visible.append({"role": "user", "content": content_text(message.content)})
        elif isinstance(message, AIMessage) and not message.tool_calls:
            if i + 1 == len(messages) or isinstance(messages[i + 1], HumanMessage):
                if text := content_text(message.content):
                    visible.append({"role": "assistant", "content": text})
    return visible
