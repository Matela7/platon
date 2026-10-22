"""Load the project's Gmail stdio server for the synchronous agent runtime."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from threading import RLock
from typing import Any

import anyio
from anyio.from_thread import start_blocking_portal
from langchain_core.tools import BaseTool, StructuredTool, ToolException


class GmailMCP:
    """One persistent event loop and MCP session, opened lazily and closed explicitly.

    Only tools/list runs during discovery. OAuth remains the server owner's job.
    The portal propagates contextvars and keeps async resources on their own loop.
    """

    def __init__(self, config_path: Path, timeout: float = 120):
        self.config_path = Path(config_path)
        self.timeout = timeout
        self._stack = ExitStack()
        self._lock = RLock()
        self._tools: list[BaseTool] | None = None
        self._closed = False

    async def _bounded(self, function, *args):
        with anyio.fail_after(self.timeout):
            return await function(*args)

    def tools(self) -> list[BaseTool]:
        with self._lock:
            if self._closed:
                raise RuntimeError("Gmail MCP connection is closed.")
            if self._tools is not None:
                return self._tools
            # Import the optional transport only when Gmail is actually delegated.
            from fastmcp import Client
            from fastmcp.client.transports import StdioTransport
            from langchain.mcp import MCPAdapter

            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            server = data["mcpServers"]["gmail"]
            if server.get("type", server.get("transport", "stdio")) != "stdio":
                raise ValueError("Platon Gmail currently supports stdio MCP only.")
            command = server["command"]
            if os.name == "nt" and command == "npx":
                command = "npx.cmd"
            transport = StdioTransport(
                command=command, args=server.get("args", []),
                env={**os.environ, **server.get("env", {})},
                cwd=str((self.config_path.parent / server.get("cwd", ".")).resolve()),
            )
            try:
                self._portal = self._stack.enter_context(start_blocking_portal())
                adapter = MCPAdapter(Client(transport, timeout=self.timeout))
                self._stack.enter_context(self._portal.wrap_async_context_manager(adapter))
                remote = self._portal.call(self._bounded, adapter.list_tools)
                allowed, disabled = server.get("allowedTools"), server.get("disabledTools")
                if allowed is not None and disabled is not None:
                    raise ValueError("Use either allowedTools or disabledTools, not both.")
                self._tools = [self._sync_tool(tool) for tool in remote
                               if (allowed is None or tool.name in allowed)
                               and tool.name not in (disabled or [])]
                if not self._tools:
                    raise ValueError("Gmail MCP exposed no tools; check configuration and OAuth scopes.")
                return self._tools
            except BaseException:
                self._stack.close()
                self._tools = None
                raise

    def _sync_tool(self, remote: BaseTool) -> BaseTool:
        def execute(**arguments: Any):
            with self._lock:
                if self._closed:
                    raise ToolException("Gmail MCP connection is closed.")
                try:
                    # Call the coroutine directly to preserve content AND artifact,
                    # and let the copied handler preserve MCP isError semantics.
                    return self._portal.call(self._bounded, remote.coroutine, **{}) if False else self._call(remote, arguments)
                except TimeoutError as exc:
                    raise ToolException(
                        "Gmail MCP timed out. The outcome may be unknown; verify state before retrying a mutation."
                    ) from exc

        return StructuredTool(
            name=remote.name, description=remote.description, args_schema=remote.args_schema,
            func=execute, response_format=remote.response_format,
            metadata=remote.metadata, handle_tool_error=remote.handle_tool_error,
        )

    def _call(self, remote, arguments):
        async def invoke():
            return await remote.coroutine(**arguments)
        return self._portal.call(self._bounded, invoke)

    def close(self):
        with self._lock:
            self._closed = True
            self._stack.close()
