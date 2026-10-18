from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool

from platon.agent.tools.common import configure_error_handling, truncate_output
from platon.agent.tools.errors import ToolError
from platon.app_logging import LOGGER, log_call


READ_LIMITS = {"small": 2_000, "standard": 6_000, "expanded": 12_000, "deep": 30_000}


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

    @tool("file_search")
    @log_call
    def file_search(pattern: str, dir_path: str = ".") -> str:
        """Find workspace files matching a glob pattern."""
        return discover(
            "file_search",
            {"pattern": pattern, "dir_path": dir_path},
        )

    return tuple(configure_error_handling(tool) for tool in (ls, glob))


def create_file_management_tools(
    root_dir: Path,
    max_output_chars: int = 20_000,
) -> tuple[BaseTool, ...]:
    """Create a file toolkit restricted to a single resolved workspace root."""
    workspace_root = root_dir.expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    def resolve(path: str) -> Path:
        if workspace_root.name == "documents" and (path == "/documents" or path.startswith("/documents/")):
            path = path[len("/documents"):].lstrip("/") or "."
        target = (workspace_root / path).resolve()
        if not target.is_relative_to(workspace_root):
            raise ValueError(f"Path is outside the configured workspace: {path}")
        return target

    def invoke_file_tool(tool_name: str, arguments: dict[str, Any]) -> str:
        LOGGER.info("Starting workspace file operation (tool=%s)", tool_name)
        try:
            match tool_name:
                case "read_file":
                    target = resolve(arguments["file_path"])
                    start_page, end_page = arguments["start_page"], arguments["end_page"]
                    if start_page < 1 or (end_page is not None and end_page < start_page):
                        raise ValueError("Pages are one-based and end_page must be at least start_page")
                    if target.suffix.lower() == ".pdf":
                        from pypdf import PdfReader

                        reader = PdfReader(target)
                        if start_page > len(reader.pages):
                            raise ValueError(f"start_page exceeds the document's {len(reader.pages)} pages")
                        result = "\n\n".join(
                            f"[Page {index + 1}]\n{reader.pages[index].extract_text() or ''}"
                            for index in range(start_page - 1, min(end_page or len(reader.pages), len(reader.pages)))
                        )
                    elif target.suffix.lower() == ".docx":
                        if start_page != 1 or end_page not in (None, 1):
                            raise ValueError("DOCX has no reliable page layout; use start_page=1 and end_page=None")
                        from docx import Document

                        document = Document(target)
                        result = "\n".join([
                            *(paragraph.text for paragraph in document.paragraphs),
                            *("\t".join(cell.text for cell in row.cells)
                              for table in document.tables for row in table.rows),
                        ])
                    else:
                        pages = target.read_text(encoding="utf-8").split("\f")
                        if start_page > len(pages):
                            raise ValueError(f"start_page exceeds the document's {len(pages)} pages")
                        result = "\f".join(pages[start_page - 1:end_page])
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
            limit = READ_LIMITS[arguments["mode"]] if tool_name == "read_file" else max_output_chars
            return truncate_output(result, limit)
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
    def read_file(
        file_path: str,
        start_page: int = 1,
        end_page: int | None = None,
        mode: Literal["small", "standard", "expanded", "deep"] = "standard",
    ) -> str:
        """Read PDF, DOCX or UTF-8 text from the configured workspace.

        Page bounds are inclusive and one-based; text pages use form-feed separators.
        DOCX returns paragraphs/tables without page layout; keep the default page range.
        Output budgets: small=2000, standard=6000, expanded=12000, deep=30000 characters.
        """
        return invoke_file_tool("read_file", {
            "file_path": file_path, "start_page": start_page, "end_page": end_page, "mode": mode,
        })

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
