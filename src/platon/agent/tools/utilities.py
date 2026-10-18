from datetime import datetime
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from platon.agent.tools.common import configure_error_handling
from platon.agent.tools.errors import ToolError
from platon.agent.tools.interaction import ask_user
from platon.app_logging import log_call


def create_utils_tools() -> tuple[BaseTool, ...]:
    @tool
    @log_call
    def get_current_time() -> str:
        """Get the current date and time in ISO 8601 format."""
        try:
            return datetime.now().astimezone().isoformat()
        except Exception as exc:
            raise ToolError.from_exception(
                "get_current_time",
                "reading the current local time",
                exc,
            ) from exc

    @tool
    @log_call
    def get_system_path() -> str:
        """Get the current working directory path."""
        try:
            return str(Path.cwd())
        except Exception as exc:
            raise ToolError.from_exception(
                "get_system_path",
                "reading the current working directory",
                exc,
            ) from exc

    @tool
    @log_call
    def execute_ls_command(path: str) -> str:
        """List entries in a directory without executing a shell command."""
        try:
            target = Path(path).expanduser().resolve()
            if not target.is_dir():
                raise NotADirectoryError(f"Not a directory: {target}")
            return "\n".join(sorted(entry.name for entry in target.iterdir()))
        except Exception as exc:
            raise ToolError.from_exception(
                "execute_ls_command",
                f"listing directory '{path}'",
                exc,
            ) from exc

    return tuple(
        configure_error_handling(tool_instance)
        for tool_instance in (get_current_time, get_system_path, execute_ls_command, ask_user)
    )
