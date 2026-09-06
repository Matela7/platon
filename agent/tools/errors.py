from __future__ import annotations

from langchain_core.tools import ToolException


class ToolError(ToolException):
    """Error raised by an agent tool with operation and cause details."""

    def __init__(
        self,
        tool_name: str,
        operation: str,
        message: str,
        *,
        cause: Exception | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.operation = operation
        self.cause = cause

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
