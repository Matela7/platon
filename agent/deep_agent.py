"""Deep agent with local skills and file-backed memory."""

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import FileInfo
from deepagents.middleware.summarization import (
    SummarizationMiddleware,
)
from agent.base_agent import BaseAgent
from agent.prompt_loader import load_prompt
from agent.tools.tools import ask_user


class _LocalFilesystemBackend(FilesystemBackend):
    def ls_info(self, path: str) -> list[FileInfo]:
        """Normalize virtual paths returned by deepagents 0.3.x on Windows."""
        entries = super().ls_info(path)
        for entry in entries:
            entry["path"] = "/" + entry["path"].replace("\\", "/").lstrip("/")
        return entries


class DeepAgent(BaseAgent):
    agent_name = "deep_agent"

    def _default_prompt(self) -> str:
        return load_prompt(self.config.system_prompt)

    def create_agent(self) -> Any:
        tools = list(self.tools_list)
        if not any(tool.name == ask_user.name for tool in tools):
            tools.append(ask_user)
        return create_deep_agent(
            model=self.model,
            tools=tools,
            system_prompt=self.prompt or self._default_prompt(),
            middleware=self._middleware(),
            checkpointer=self.checkpointer,
            backend=_LocalFilesystemBackend(root_dir=self.config.backend_root, virtual_mode=True),
            skills=self.config.skills,
            memory=self.config.memory,
            name=self.agent_name,
            debug=self.config.debug,
        )
