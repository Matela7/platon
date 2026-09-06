from __future__ import annotations

import json
import ipaddress
import os
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urljoin, urlparse

import requests
from langchain_community.agent_toolkits import FileManagementToolkit
from langchain_community.tools import ShellTool
from langchain_experimental.tools import PythonREPLTool
from langchain_core.tools import BaseTool, tool
from pydantic import Field

from agent.tools.errors import ToolError
from websearch.websearch_module import WebSearch
from websearch.websearch_parameters import DuckDuckGoTime, WebSearchParameters

if TYPE_CHECKING:
    from vectorstore.client_manager import ClientManager


def _configure_error_handling(tool_instance: BaseTool) -> BaseTool:
    """Return tool failures to the model as readable ToolMessage content."""
    tool_instance.handle_tool_error = True
    tool_instance.handle_validation_error = (
        lambda exc: f"Tool '{tool_instance.name}' received invalid arguments: {exc}"
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


def create_rag_tools(cm: ClientManager) -> tuple[BaseTool, ...]:
    """Create tools backed by the private vector-store client."""

    @tool
    def search_collection(collection_name: str, query: str, n_results: int = 5) -> list:
        """Search a specific collection using the ClientManager."""
        try:
            return cm.search(collection_name, query, n_results)
        except Exception as exc:
            raise ToolError.from_exception(
                "search_collection",
                f"searching collection '{collection_name}'",
                exc,
            ) from exc

    @tool
    def search_all_collections(
        query: str,
        n_results: int = 5,
        n_results_per_collection: int = 5,
    ) -> list:
        """Search all collections using the ClientManager."""
        try:
            return cm.search_all(query, n_results, n_results_per_collection)
        except Exception as exc:
            raise ToolError.from_exception(
                "search_all_collections",
                "searching all collections",
                exc,
            ) from exc

    @tool
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
        for tool_instance in (get_current_time, get_system_path, execute_ls_command)
    )


def create_http_tools(max_output_chars: int = 20_000) -> tuple[BaseTool, ...]:
    """Create bounded public HTTP tools with readable failure messages."""

    @tool("http_get")
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
    toolkit = FileManagementToolkit(root_dir=str(workspace_root))
    toolkit_tools = {
        tool_instance.name: tool_instance
        for tool_instance in toolkit.get_tools()
    }

    def invoke_file_tool(tool_name: str, arguments: dict[str, Any]) -> str:
        try:
            result = toolkit_tools[tool_name].invoke(arguments)
            return _truncate_output(result, max_output_chars)
        except Exception as exc:
            raise ToolError.from_exception(
                tool_name,
                f"accessing workspace '{workspace_root}'",
                exc,
            ) from exc

    @tool("copy_file")
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
    def file_delete(file_path: str) -> str:
        """Delete a file within the configured workspace."""
        return invoke_file_tool("file_delete", {"file_path": file_path})

    @tool("file_search")
    def file_search(pattern: str, dir_path: str = ".") -> str:
        """Find workspace files matching a glob pattern."""
        return invoke_file_tool(
            "file_search",
            {"pattern": pattern, "dir_path": dir_path},
        )

    @tool("move_file")
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
    def read_file(file_path: str) -> str:
        """Read a UTF-8 text file from the configured workspace."""
        return invoke_file_tool("read_file", {"file_path": file_path})

    @tool("write_file")
    def write_file(file_path: str, text: str, append: bool = False) -> str:
        """Write or append UTF-8 text within the configured workspace."""
        return invoke_file_tool(
            "write_file",
            {"file_path": file_path, "text": text, "append": append},
        )

    @tool("list_directory")
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
) -> tuple[BaseTool, ...]:
    """Create host shell and Python tools for the execution subagent."""
    workspace_root = working_dir.expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    shell_tool = ShellTool()
    python_tool = PythonREPLTool()

    @tool("run_shell")
    def run_shell(command: str) -> str:
        """Run a shell command on the host, starting in the workspace."""
        try:
            if os.name == "nt":
                scoped_command = (
                    f'cd /d "{workspace_root}" && {command}'
                )
            else:
                escaped_root = str(workspace_root).replace("'", "'\"'\"'")
                scoped_command = f"cd -- '{escaped_root}' && {command}"

            result = shell_tool.run(scoped_command)
            if result is None:
                raise RuntimeError("ShellTool returned no output after a failure.")
            if "returned non-zero exit status" in result:
                raise RuntimeError(result)
            return _truncate_output(result, max_output_chars)
        except Exception as exc:
            raise ToolError.from_exception(
                "run_shell",
                f"executing shell command in '{workspace_root}'",
                exc,
            ) from exc

    @tool("run_python")
    def run_python(code: str) -> str:
        """Run Python code on the host, starting in the workspace."""
        try:
            scoped_code = (
                "import os as _agent_os\n"
                f"_agent_os.chdir({str(workspace_root)!r})\n"
                f"{code}"
            )
            result = python_tool.run(scoped_code)
            if result is None:
                raise RuntimeError("PythonREPLTool returned no output.")
            if re.match(
                r"^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)\(",
                result.strip(),
            ):
                raise RuntimeError(result)
            return _truncate_output(result, max_output_chars)
        except Exception as exc:
            raise ToolError.from_exception(
                "run_python",
                f"executing Python code in '{workspace_root}'",
                exc,
            ) from exc

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
