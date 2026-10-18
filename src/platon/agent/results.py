"""Small, factual reports shared by delegation, persistence and the UI."""

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from platon.agent.tools.errors import error_details


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


def _tool_output(message: ToolMessage) -> Any:
    output = message.artifact if message.artifact is not None else content_text(message.content)
    if isinstance(output, str):
        try:
            return json.loads(output)
        except (ValueError, TypeError):
            pass
    return output


def _tool_status(message: ToolMessage) -> str:
    output = _tool_output(message)
    if message.status == "error":
        return "error"
    return output.get("status", message.status) if isinstance(output, dict) else message.status


def execution_report(messages: list[BaseMessage], error: Exception | None = None) -> dict[str, Any]:
    turn = current_turn(messages)
    evidence = []
    errors = []
    call_args = {
        call["id"]: call.get("args", {})
        for message in turn if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    for index, message in enumerate(turn):
        if not isinstance(message, ToolMessage):
            continue
        output = _tool_output(message)
        status = _tool_status(message)
        evidence.append({"tool": message.name, "status": status, "output": output})
        if status in {"error", "partial"}:
            tool_errors = ((output.get("errors", []) if isinstance(output, dict) else [])
                           or [{"message": "Delegated work is incomplete." if status == "partial"
                               else content_text(message.content) or "Tool failed."}])
            # Invalid arguments execute nothing. A corrected, successful call resolves them;
            # preserve the failed call in evidence without reporting a failed final task.
            recovered_validation = all(isinstance(item, dict) and item.get("category") == "validation" for item in tool_errors) and any(
                isinstance(later, ToolMessage) and later.name == message.name
                and _tool_status(later) not in {"error", "partial"}
                for later in turn[index + 1:]
            )
            # Searching a collection before it is ingested can fail legitimately.
            # A later successful search of that same collection resolves the lookup,
            # even when the tool encoded the failure in a successful ToolMessage.
            failed_args = call_args.get(message.tool_call_id, {})
            recovered_lookup = (
                message.name == "search_collection"
                and isinstance(failed_args, dict)
                and bool(failed_args.get("collection_name"))
                and all(isinstance(item, dict) and item.get("category") == "lookup" for item in tool_errors)
                and any(
                    isinstance(later, ToolMessage)
                    and later.name == "search_collection"
                    and _tool_status(later) not in {"error", "partial"}
                    and call_args.get(later.tool_call_id, {}).get("collection_name") == failed_args["collection_name"]
                    for later in turn[index + 1:]
                )
            )
            if not (recovered_validation or recovered_lookup):
                errors.extend(tool_errors)
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
