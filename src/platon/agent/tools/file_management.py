from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from platon.agent.tools.common import configure_error_handling, truncate_output
from platon.agent.tools.errors import ToolError
from platon.app_logging import LOGGER, log_call


def create_document_discovery_tools(
    root_dir: Path,
    max_output_chars: int = 20_000,
) -> tuple[BaseTool, ...]:
    """Find documents and return host paths accepted by ingestion tools."""
    documents_root = root_dir.expanduser().resolve()
    documents_root.mkdir(parents=True, exist_ok=True)

    def discover(tool_name: str, path: str, pattern: str | None = None) -> str:
        try:
            if path == "/documents" or path.startswith("/documents/"):
                path = path[len("/documents"):].lstrip("/") or "."
            directory = documents_root if path == "/" else (documents_root / path).resolve()
            if not directory.is_relative_to(documents_root):
                raise ValueError(f"Path is outside the documents directory: {path}")
            matches = directory.iterdir() if pattern is None else directory.glob(pattern)
            paths = sorted({
                str(match.resolve()) for match in matches
                if match.resolve().is_relative_to(documents_root)
            })
            return truncate_output("\n".join(paths), max_output_chars)
        except Exception as exc:
            raise ToolError.from_exception(
                tool_name, f"finding documents in '{documents_root}'", exc,
            ) from exc

    @tool("ls")
    @log_call
    def ls(path: str = ".") -> str:
        """List local documents, returning absolute host paths. Default path is the documents directory.

        /documents is an alias for the documents directory, not the shared filesystem.
        Pass a returned file path unchanged as file_path to add_document_to_collection.
        This tool lists paths only; it does not read file contents.
        """
        return discover("ls", path)

    @tool("glob")
    @log_call
    def glob(pattern: str, path: str = ".") -> str:
        """Find local documents by glob pattern, e.g. *.pdf or **/*.pdf.

        Default path is the documents directory; /documents is an alias for it.
        Results are absolute host paths;
        pass a file path unchanged as file_path to add_document_to_collection.
        """
        return discover("glob", path, pattern)

    return tuple(configure_error_handling(tool) for tool in (ls, glob))


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
            return truncate_output(result, max_output_chars)
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
        configure_error_handling(tool_instance)
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
