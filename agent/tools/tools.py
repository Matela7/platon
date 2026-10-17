from __future__ import annotations

import json
import ipaddress
import os
import socket
import shutil
import subprocess
import sys
import signal
from time import monotonic
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urljoin, urlparse

import requests
from langchain_core.tools import BaseTool, tool

from app_logging import LOGGER, log_call
from langgraph.types import interrupt
from pydantic import Field

from agent.tools.errors import ToolError, error_details
from agent.cancellation import RunStopped, current_stop_event
from websearch.websearch_parameters import DuckDuckGoTime, WebSearchParameters

if TYPE_CHECKING:
    from vectorstore.client_manager import ClientManager


@tool
def ask_user(question: str) -> str:
    """Ask one focused question when missing information blocks a correct result."""
    LOGGER.info("Workflow awaiting user clarification")
    response = interrupt({"kind": "clarification", "question": question})
    return response["answer"]


def _configure_error_handling(tool_instance: BaseTool) -> BaseTool:
    """Return tool failures to the model as readable ToolMessage content."""
    def report_error(exc):
        exc.retry_safe = tool_instance.name in {
            "search_web", "http_get", "search_collection", "search_all_collections",
            "get_list_of_collections", "read_file", "file_search", "list_directory",
        }
        return json.dumps({"status": "error", "errors": [error_details(exc)]}, ensure_ascii=False)

    tool_instance.handle_tool_error = report_error
    tool_instance.handle_validation_error = (
        lambda exc: json.dumps({"status": "error", "errors": [{
            "tool": tool_instance.name, "category": "validation", "message": str(exc), "retryable": False,
        }]})
    )
    return tool_instance


def _truncate_output(value: Any, max_chars: int) -> str:
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


def _validate_http_url(url: str, tool_name: str) -> str:
    """Allow only absolute public HTTP(S) destinations."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "Only absolute http:// and https:// URLs are supported.",
        )
    if parsed.username is not None or parsed.password is not None:
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "Credentials embedded in URLs are not supported.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "The URL must contain a hostname.",
        )

    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(
                    hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except OSError as exc:
            raise ToolError.from_exception(
                tool_name,
                f"resolving hostname '{hostname}'",
                exc,
            ) from exc

    if not addresses or any(not address.is_global for address in addresses):
        raise ToolError(
            tool_name,
            f"validating URL '{url}'",
            "Private, loopback, link-local, and reserved destinations are blocked.",
        )
    return url


@log_call
def _request_text(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    max_redirects: int = 3,
) -> str:
    """Perform a bounded request while validating every redirect destination."""
    current_url = url
    for redirect_count in range(max_redirects + 1):
        response = requests.request(
            method,
            current_url,
            json=data if method == "POST" else None,
            headers={
                "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.8",
                "User-Agent": "PlatonResearchAgent/1.0",
            },
            timeout=(5, 20),
            allow_redirects=False,
        )
        if not response.is_redirect:
            response.raise_for_status()
            return response.text or f"HTTP {response.status_code}: empty response body"

        location = response.headers.get("Location")
        if not location:
            response.raise_for_status()
            return response.text
        if method == "POST":
            raise ToolError(
                "http_post",
                f"following redirect from '{current_url}'",
                "POST redirects are not followed automatically.",
            )
        if redirect_count >= max_redirects:
            raise requests.TooManyRedirects(
                f"More than {max_redirects} redirects for {url}"
            )
        current_url = _validate_http_url(
            urljoin(current_url, location),
            "http_get",
        )

    raise requests.TooManyRedirects(f"More than {max_redirects} redirects for {url}")


def create_rag_tools(cm: ClientManager, max_output_chars: int = 20_000) -> tuple[BaseTool, ...]:
    """Create tools backed by the private vector-store client."""

    def bounded_results(results):
        if not results:
            return results
        allowance = max(1, max_output_chars // len(results))
        return [{**item, "document": _truncate_output(item["document"], allowance)}
                if isinstance(item, dict) and "document" in item else item for item in results]

    @tool
    @log_call
    def search_collection(collection_name: str, query: str, n_results: Annotated[int, Field(ge=1, le=50)] = 5) -> list:
        """Search a specific collection using the ClientManager."""
        try:
            return bounded_results(cm.search(collection_name, query, n_results))
        except Exception as exc:
            raise ToolError.from_exception(
                "search_collection",
                f"searching collection '{collection_name}'",
                exc,
            ) from exc

    @tool
    @log_call
    def search_all_collections(
        query: str,
        n_results: Annotated[int, Field(ge=1, le=50)] = 5,
        n_results_per_collection: Annotated[int, Field(ge=1, le=50)] = 5,
    ) -> list:
        """Search all collections using the ClientManager."""
        try:
            return bounded_results(cm.search_all(query, n_results, n_results_per_collection))
        except Exception as exc:
            if hasattr(exc, "partial_results"):
                exc.partial_results = bounded_results(exc.partial_results[:n_results])
            raise ToolError.from_exception(
                "search_all_collections",
                "searching all collections",
                exc,
            ) from exc

    @tool
    @log_call
    def get_list_of_collections() -> list[str]:
        """Get a list of all collection names."""
        try:
            return cm.get_collections()
        except Exception as exc:
            raise ToolError.from_exception(
                "get_list_of_collections",
                "listing collections",
                exc,
            ) from exc

    @tool
    @log_call
    def add_document_to_collection(collection_name: str, file_path: str, doc_name: str) -> bool:
        """Add a document to a specific collection."""
        try:
            return cm.add_document_to_collection(collection_name, file_path, doc_name)
        except Exception as exc:
            raise ToolError.from_exception(
                "add_document_to_collection",
                f"adding document '{doc_name}' to collection '{collection_name}'",
                exc,
            ) from exc

    return tuple(
        _configure_error_handling(tool_instance)
        for tool_instance in (
            search_collection,
            search_all_collections,
            get_list_of_collections,
            add_document_to_collection,
        )
    )


def create_web_search_tools() -> tuple[BaseTool, ...]:
    """Create ranked DuckDuckGo discovery tools for public-web research."""

    @tool
    @log_call
    def search_web(
        query: str,
        max_results: int = 15,
        top_k: int = 5,
        region: str = "wt-wt",
        time: Annotated[
            DuckDuckGoTime,
            Field(
                description=(
                    "DuckDuckGo result-age window: 'd' for the last day, 'w' "
                    "for the last week, 'm' for the last month, or 'y' for the "
                    "last year. Pass null for no age filter. This is not a "
                    "date, current time, timestamp, or filter object."
                )
            ),
        ] = None,
        source: str = "text",
    ) -> dict[str, Any]:
        """Search DuckDuckGo and return deduplicated, relevance-ranked public results."""
        try:
            from websearch.websearch_module import WebSearch

            parameters = WebSearchParameters(
                query=query,
                max_results=max_results,
                top_k=top_k,
                region=region,
                time=time,
                source=source,
            )
            return {"query": query, "results": WebSearch(parameters).search()}
        except Exception as exc:
            raise ToolError.from_exception(
                "search_web",
                f"searching the web for '{query}'",
                exc,
            ) from exc

    return (_configure_error_handling(search_web),)


def create_search_tools(cm: ClientManager) -> tuple[BaseTool, ...]:
    """Backward-compatible aggregate; new agents use narrower factories."""
    return (*create_rag_tools(cm), *create_web_search_tools())


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
        _configure_error_handling(tool_instance)
        for tool_instance in (get_current_time, get_system_path, execute_ls_command, ask_user)
    )


def create_http_tools(max_output_chars: int = 20_000) -> tuple[BaseTool, ...]:
    """Create bounded public HTTP tools with readable failure messages."""

    @tool("http_get")
    @log_call
    def http_get(url: str) -> str:
        """Fetch an absolute HTTP(S) URL with a GET request."""
        try:
            validated_url = _validate_http_url(url, "http_get")
            return _truncate_output(
                _request_text("GET", validated_url),
                max_output_chars,
            )
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError.from_exception(
                "http_get",
                f"performing GET request to '{url}'",
                exc,
            ) from exc

    @tool("http_post")
    @log_call
    def http_post(url: str, data: dict[str, Any]) -> str:
        """Send JSON-compatible data to an absolute HTTP(S) URL with POST."""
        try:
            validated_url = _validate_http_url(url, "http_post")
            return _truncate_output(
                _request_text("POST", validated_url, data=data),
                max_output_chars,
            )
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError.from_exception(
                "http_post",
                f"performing POST request to '{url}'",
                exc,
            ) from exc

    return tuple(
        _configure_error_handling(tool_instance)
        for tool_instance in (http_get, http_post)
    )


def create_file_management_tools(
    root_dir: Path,
    max_output_chars: int = 20_000,
) -> tuple[BaseTool, ...]:
    """Create a file toolkit restricted to a single resolved workspace root."""
    workspace_root = root_dir.expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    def resolve(path: str) -> Path:
        target = (workspace_root / path).resolve()
        if not target.is_relative_to(workspace_root):
            raise ValueError(f"Path is outside the configured workspace: {path}")
        return target

    def invoke_file_tool(tool_name: str, arguments: dict[str, Any]) -> str:
        LOGGER.info("Starting workspace file operation (tool=%s)", tool_name)
        try:
            match tool_name:
                case "read_file":
                    result = resolve(arguments["file_path"]).read_text(encoding="utf-8")
                case "write_file":
                    target = resolve(arguments["file_path"])
                    with target.open("a" if arguments["append"] else "w", encoding="utf-8") as file:
                        file.write(arguments["text"])
                    result = f"Wrote {arguments['file_path']}"
                case "list_directory":
                    result = "\n".join(sorted(p.name for p in resolve(arguments["dir_path"]).iterdir()))
                case "file_search":
                    matches = resolve(arguments["dir_path"]).rglob(arguments["pattern"])
                    result = "\n".join(str(p.relative_to(workspace_root)) for p in matches
                                       if p.resolve().is_relative_to(workspace_root))
                case "file_delete":
                    resolve(arguments["file_path"]).unlink()
                    result = f"Deleted {arguments['file_path']}"
                case "copy_file" | "move_file":
                    source = resolve(arguments["source_path"])
                    destination = resolve(arguments["destination_path"])
                    if not source.is_file():
                        raise ValueError("Only files can be copied or moved.")
                    if destination.is_dir():
                        destination = resolve(str(destination / source.name))
                    if tool_name == "copy_file":
                        shutil.copy2(source, destination)
                    else:
                        shutil.move(source, destination)
                    result = f"{tool_name}: {arguments['source_path']} -> {arguments['destination_path']}"
                case _:
                    raise ValueError(f"Unknown file operation: {tool_name}")
            LOGGER.info("Workspace file operation completed (tool=%s)", tool_name)
            return _truncate_output(result, max_output_chars)
        except Exception as exc:
            LOGGER.error("Workspace file operation failed (tool=%s, exception=%s)", tool_name, type(exc).__name__)
            raise ToolError.from_exception(
                tool_name,
                f"{tool_name} with {arguments!r} in workspace '{workspace_root}'",
                exc,
            ) from exc

    @tool("copy_file")
    @log_call
    def copy_file(source_path: str, destination_path: str) -> str:
        """Copy a file within the configured workspace."""
        return invoke_file_tool(
            "copy_file",
            {
                "source_path": source_path,
                "destination_path": destination_path,
            },
        )

    @tool("file_delete")
    @log_call
    def file_delete(file_path: str) -> str:
        """Delete a file within the configured workspace."""
        return invoke_file_tool("file_delete", {"file_path": file_path})

    @tool("file_search")
    @log_call
    def file_search(pattern: str, dir_path: str = ".") -> str:
        """Find workspace files matching a glob pattern."""
        return invoke_file_tool(
            "file_search",
            {"pattern": pattern, "dir_path": dir_path},
        )

    @tool("move_file")
    @log_call
    def move_file(source_path: str, destination_path: str) -> str:
        """Move a file within the configured workspace."""
        return invoke_file_tool(
            "move_file",
            {
                "source_path": source_path,
                "destination_path": destination_path,
            },
        )

    @tool("read_file")
    @log_call
    def read_file(file_path: str) -> str:
        """Read a UTF-8 text file from the configured workspace."""
        return invoke_file_tool("read_file", {"file_path": file_path})

    @tool("write_file")
    @log_call
    def write_file(file_path: str, text: str, append: bool = False) -> str:
        """Write or append UTF-8 text within the configured workspace."""
        return invoke_file_tool(
            "write_file",
            {"file_path": file_path, "text": text, "append": append},
        )

    @tool("list_directory")
    @log_call
    def list_directory(dir_path: str = ".") -> str:
        """List a directory within the configured workspace."""
        return invoke_file_tool("list_directory", {"dir_path": dir_path})

    return tuple(
        _configure_error_handling(tool_instance)
        for tool_instance in (
            copy_file,
            file_delete,
            file_search,
            move_file,
            read_file,
            write_file,
            list_directory,
        )
    )


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
            output = _truncate_output(result.stdout + result.stderr, max_output_chars)
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
            exc.partial_results = [{"tool": tool_name, "output": _truncate_output(output, max_output_chars)}] if output else []
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
        _configure_error_handling(tool_instance)
        for tool_instance in (run_shell, run_python)
    )


def create_default_tools(cm: ClientManager) -> list[BaseTool]:
    """Backward-compatible aggregate for callers outside the agent hierarchy."""
    all_tools = (*create_search_tools(cm), *create_utils_tools())
    tools_by_name = {tool_instance.name: tool_instance for tool_instance in all_tools}
    default_names = (
        "search_collection",
        "search_all_collections",
        "get_list_of_collections",
        "search_web",
        "get_current_time",
    )
    return [tools_by_name[name] for name in default_names]
