"""Coding agent with workspace and execution capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.workflow_agent import WorkflowAgent
from agent.models.agent_config import AgentConfig
from agent.prompt_loader import load_prompt
from agent.tools.tools import create_execution_tools, create_file_management_tools


class CodingAgent(WorkflowAgent):
    """Inspect, edit, and execute code inside the configured workspace."""

    agent_name = "coding_agent"
    prompt_path = "agents/coding.md"
    delegation_description = (
        "Delegate workspace inspection, file changes, code execution, calculations, and report creation. "
        "Use this specialist for concrete work on local files or when another specialist's findings must be "
        "written to an artifact. It can verify changes and consume automatically supplied research or database "
        "reports, but it cannot browse the web or query private collections."
    )
    read_only_tools = frozenset({"read_file", "file_search", "list_directory"})

    def __init__(
        self,
        model: BaseChatModel,
        working_dir: Path,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.working_dir = working_dir.expanduser().resolve()
        super().__init__(
            model=model,
            config=config,
            tools_list=tools_list,
            prompt=prompt,
            checkpointer=checkpointer,
        )
        self.max_tool_calls = self.config.coding_tool_limit
        if tools_list is None:
            tools_list = [
                *create_file_management_tools(
                    self.working_dir,
                    self.config.max_tool_output_chars,
                ),
                *create_execution_tools(
                    self.working_dir,
                    self.config.max_tool_output_chars,
                    self.config.execution_timeout_seconds,
                ),
            ]
            self.tools_list = tools_list
        if prompt is None:
            self.prompt = self._workspace_prompt()

    def _workspace_prompt(self) -> str:
        return load_prompt(self.prompt_path).replace("{workspace_root}", str(self.working_dir))
