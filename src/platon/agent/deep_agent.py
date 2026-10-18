"""Deep agent with local skills and file-backed memory."""

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from platon.agent.base_agent import BaseAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.prompt_loader import load_prompt
from platon.agent.tools.interaction import ask_user


class DeepAgent(BaseAgent):
    agent_name = "deep_agent"

    def __init__(
        self,
        model: BaseChatModel,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
        *,
        subagent_model: BaseChatModel | None = None,
    ) -> None:
        super().__init__(model, config, tools_list, prompt, checkpointer)
        self.subagent_model = subagent_model

    def _default_prompt(self) -> str:
        return load_prompt(self.config.system_prompt)

    def create_agent(self) -> Any:
        root = self.config.backend_root
        if "/skills/" in self.config.skills:
            (root / "skills").mkdir(parents=True, exist_ok=True)
        if "/memory/AGENTS.md" in self.config.memory:
            memory_file = root / "memory" / "AGENTS.md"
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                with memory_file.open("x", encoding="utf-8") as stream:
                    stream.write("# Agent memory\n\nNo saved project context yet.\n")
            except FileExistsError:
                pass  # Keep all existing user and agent memory.
        tools = list(self.tools_list)
        if not any(tool.name == ask_user.name for tool in tools):
            tools.append(ask_user)
        return create_deep_agent(
            model=self.model,
            subagents=[{
                "name": "general-purpose",
                "description": "Delegate a bounded task requiring independent work and context.",
                "system_prompt": self.prompt or self._default_prompt(),
                "model": self.subagent_model if self.subagent_model is not None else self.model,
                "tools": tools,
                "middleware": self._middleware(),
                "skills": self.config.skills,
            }],
            tools=tools,
            system_prompt=self.prompt or self._default_prompt(),
            middleware=self._middleware(),
            checkpointer=self.checkpointer,
            backend=FilesystemBackend(root_dir=self.config.backend_root, virtual_mode=True),
            skills=self.config.skills,
            memory=self.config.memory,
            name=self.agent_name,
            debug=self.config.debug,
        )
