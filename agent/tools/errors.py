from __future__ import annotations

import subprocess

import requests
from langchain_core.tools import ToolException


def error_details(exc: Exception) -> dict:
    cause = exc
    partial_results = []
    remaining_collections = []
    seen = set()
    while id(cause) not in seen:
        seen.add(id(cause))
        partial_results = getattr(cause, "partial_results", None) or partial_results
        remaining_collections = getattr(cause, "remaining_collections", None) or remaining_collections
        nested = getattr(cause, "cause", None) or cause.__cause__
        if nested is None:
            break
        cause = nested
    if isinstance(cause, (requests.Timeout, requests.ConnectionError, TimeoutError)):
        category = "transient"
    elif isinstance(cause, requests.HTTPError) and cause.response is not None:
        status = cause.response.status_code
        category = "transient" if status == 429 or status >= 500 else "permission" if status in {401, 403} else "validation"
    elif isinstance(cause, PermissionError):
        category = "permission"
    elif isinstance(cause, LookupError):
        category = "lookup"
    elif isinstance(cause, subprocess.TimeoutExpired):
        category = "transient"
    elif isinstance(cause, (ValueError, FileNotFoundError)):
        category = "validation"
    else:
        category = "execution"
    return {
        "category": category,
        "message": str(exc),
        # A timeout after a mutation does not establish that retrying is safe.
        "retryable": category == "transient" and getattr(exc, "retry_safe", False),
        "operation": getattr(exc, "operation", None),
        "tool": getattr(exc, "tool_name", None),
        "partial_results": partial_results,
        "remaining_collections": remaining_collections,
    }


class ToolError(ToolException):
    """Error raised by an agent tool with operation and cause details."""

    def __init__(
        self,
        tool_name: str,
        operation: str,
        message: str,
        *,
        cause: Exception | None = None,
        retry_safe: bool = False,
    ) -> None:
        self.tool_name = tool_name
        self.operation = operation
        self.cause = cause
        self.retry_safe = retry_safe

        details = message
        if cause is not None:
            cause_details = f"{type(cause).__name__}: {cause}"
            if str(cause) != message:
                details = f"{message} Cause: {cause_details}"
            else:
                details = cause_details
        super().__init__(
            f"Tool '{tool_name}' failed while {operation}. "
            f"What happened: {details}"
        )

    @classmethod
    def from_exception(
        cls,
        tool_name: str,
        operation: str,
        exc: Exception,
    ) -> ToolError:
        if isinstance(exc, cls):
            return exc
        return cls(
            tool_name,
            operation,
            str(exc) or "Unknown error",
            cause=exc,
        )
