"""Coding agent with workspace and execution capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from platon.agent.deep_agent import DeepAgent
from platon.agent.workflow_agent import WorkflowAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.prompt_loader import load_prompt
from platon.agent.tools.execution import create_execution_tools
from platon.agent.tools.file_management import create_file_management_tools


class CodingAgent(DeepAgent, WorkflowAgent):
    """Inspect, edit, and execute code inside the configured workspace."""

    agent_name = "coding_agent"
    prompt_path = "agents/coding.md"
    delegation_description = (
        "Delegate workspace inspection, file changes, code execution, calculations, and report creation. "
        "Use this specialist for concrete work on local files or when another specialist's findings must be "
        "written to an artifact. It can verify changes and consume automatically supplied research or database "
        "reports, but it cannot browse the web or query private collections. "
        "For DOCX, PDF, or PPTX work, include in task an instruction to read and follow the matching "
        "/skills/docx/SKILL.md, /skills/pdf/SKILL.md, or /skills/pptx/SKILL.md before creating the artifact. "
        "Preserve the user's topic, language, requested length, and output format; a short document must stay short. "
        "Coding also selects relevant skills independently when the task omits skill instructions."
    )
    read_only_tools = frozenset({"ls", "read_file", "glob", "grep"})
    use_shared_filesystem = False  # Keep the SDK filesystem rooted at backend_root.

    def __init__(
        self,
        model: BaseChatModel,
        working_dir: Path,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        super().__init__(
            model=model,
            config=config,
            tools_list=tools_list,
            prompt=prompt,
            checkpointer=checkpointer,
        )
        if not self.config.skills:
            self.config = self.config.model_copy(update={"skills": ["/skills/"]})
        # Retain working_dir in the constructor for existing callers.
        self.working_dir = self.config.backend_root.expanduser().resolve()
        self.max_tool_calls = self.config.coding_tool_limit
        if tools_list is None:
            tools_list = [
                *(
                    tool for tool in create_file_management_tools(
                        self.working_dir, self.config.max_tool_output_chars,
                    ) if tool.name in {"copy_file", "move_file"}
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

    def _middleware(self) -> list[Any]:
        middleware = super()._middleware()
        for item in middleware:
            if isinstance(item, HumanInTheLoopMiddleware):
                # SDK tools are injected later, outside self.tools_list.
                item.interrupt_on.update({
                    name: {"allowed_decisions": ["approve", "reject"]}
                    for name in ("write_file", "edit_file", "delete")
                })
        return middleware

    def _workspace_prompt(self) -> str:
        return load_prompt(self.prompt_path).replace("{workspace_root}", str(self.working_dir))
