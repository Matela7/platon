from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool

from platon.agent.tools.errors import error_details


def configure_error_handling(tool_instance: BaseTool) -> BaseTool:
    """Return tool failures to the model as readable ToolMessage content."""
    def report_error(exc):
        exc.retry_safe = tool_instance.name in {
            "search_web", "http_get", "search_collection", "search_all_collections",
            "get_list_of_collections", "read_file", "file_search", "list_directory", "ls", "glob",
        }
        return json.dumps({"status": "error", "errors": [error_details(exc)]}, ensure_ascii=False)

    tool_instance.handle_tool_error = report_error
    tool_instance.handle_validation_error = (
        lambda exc: json.dumps({"status": "error", "errors": [{
            "tool": tool_instance.name, "category": "validation", "message": str(exc), "retryable": False,
        }]})
    )
    return tool_instance


def truncate_output(value: Any, max_chars: int) -> str:
    """Convert tool output to text and keep it within the model context limit."""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=True, default=str)
        except (TypeError, ValueError):
            text = str(value)

    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[Output truncated: {omitted} characters omitted.]"
