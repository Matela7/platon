from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from time import monotonic

from langchain_core.tools import BaseTool, tool

from platon.agent.cancellation import RunStopped, current_stop_event
from platon.agent.tools.common import configure_error_handling, truncate_output
from platon.agent.tools.errors import ToolError
from platon.app_logging import LOGGER, log_call


def create_execution_tools(
    working_dir: Path,
    max_output_chars: int = 20_000,
    timeout_seconds: int = 120,
) -> tuple[BaseTool, ...]:
    """Create host shell and Python tools for the execution subagent."""
    workspace_root = working_dir.expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    def run_stoppable(command, *, shell, stop_event):
        """Poll the child so Stop can terminate commands without leaving a worker busy."""
        if stop_event.is_set():
            raise RunStopped()
        process = subprocess.Popen(command, shell=shell, cwd=workspace_root, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8" if not shell else None, errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, start_new_session=os.name != "nt",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = monotonic() + timeout_seconds
        try:
            while True:
                if stop_event.is_set():
                    raise RunStopped()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                try:
                    stdout, stderr = process.communicate(timeout=min(.1, remaining))
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        except BaseException as exc:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                if process.poll() is None:
                    process.kill()
            stdout, stderr = process.communicate()
            if isinstance(exc, subprocess.TimeoutExpired):
                exc.stdout, exc.stderr = stdout, stderr
            raise

    def execute(command: str | list[str], *, shell: bool, tool_name: str) -> str:
        LOGGER.info("Starting host execution tool (tool=%s, shell=%s)", tool_name, shell)
        try:
            if stop_event := current_stop_event():
                result = run_stoppable(command, shell=shell, stop_event=stop_event)
            else:
                result = subprocess.run(
                    command, shell=shell, cwd=workspace_root, capture_output=True,
                    text=True, encoding="utf-8" if not shell else None, errors="replace", timeout=timeout_seconds,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
            output = truncate_output(result.stdout + result.stderr, max_output_chars)
            if result.returncode:
                raise ToolError(tool_name, f"running in '{workspace_root}'", f"Exit code {result.returncode}. Output: {output}")
            LOGGER.info("Host execution tool completed (tool=%s, exit_code=0)", tool_name)
            return output or "Completed successfully with no output."
        except ToolError:
            LOGGER.error("Host execution tool failed (tool=%s)", tool_name)
            raise
        except subprocess.TimeoutExpired as exc:
            LOGGER.error("Host execution tool timed out (tool=%s)", tool_name)
            output = "".join(part.decode("utf-8", errors="replace") if isinstance(part, bytes) else part or ""
                             for part in (exc.stdout, exc.stderr))
            exc.partial_results = [{"tool": tool_name, "output": truncate_output(output, max_output_chars)}] if output else []
            raise ToolError.from_exception(tool_name, f"running in '{workspace_root}'", exc) from exc
        except Exception as exc:
            LOGGER.error("Host execution tool failed (tool=%s, exception=%s)", tool_name, type(exc).__name__)
            raise ToolError.from_exception(tool_name, f"running in '{workspace_root}'", exc) from exc

    @tool("run_shell")
    @log_call
    def run_shell(command: str) -> str:
        """Run a shell command on the host, starting in the workspace."""
        return execute(command, shell=True, tool_name="run_shell")

    @tool("run_python")
    @log_call
    def run_python(code: str) -> str:
        """Run Python in a fresh process in the workspace; variables do not persist between calls."""
        return execute([sys.executable, "-c", code], shell=False, tool_name="run_python")

    return tuple(
        configure_error_handling(tool_instance)
        for tool_instance in (run_shell, run_python)
    )
