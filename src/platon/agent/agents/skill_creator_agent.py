"""Deep-agent specialist dedicated to writing reusable skills."""

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from platon.agent.deep_agent import DeepAgent
from platon.agent.prompt_loader import load_prompt


class SkillCreationGuard(AgentMiddleware):
    """Keep the built-in general-purpose subagent from bypassing this role."""

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(request.override(tools=[tool for tool in request.tools if tool.name != "task"]))

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        if request.tool_call["name"] == "task":
            return ToolMessage(content="This specialist only creates skills; delegation is disabled.",
                               tool_call_id=request.tool_call["id"], name="task", status="error")
        return handler(request)


class SkillCreatorAgent(DeepAgent):
    """Create skill files under the same /skills/ directory the supervisor reads."""

    agent_name = "skill_creator_agent"
    prompt_path = "agents/skill_creator.md"
    delegation_description = (
        "Delegate creating or updating reusable agent skills when the user explicitly requests it. "
        "This DeepAgent reads the skill-creator guide and writes SKILL.md and supporting files "
        "under /skills/ only. It cannot perform the skill's underlying task, run commands, "
        "access documents, browse the web, or update memory."
    )

    def create_agent(self) -> Any:
        root = self.config.backend_root
        (root / "skills").mkdir(parents=True, exist_ok=True)
        backend = FilesystemBackend(root_dir=root, virtual_mode=True)
        permissions = [
            FilesystemPermission(operations=["read", "write"], paths=["/skills", "/skills/**"]),
            FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny"),
        ]
        return create_deep_agent(
            model=self.model,
            system_prompt=self.prompt or load_prompt(self.prompt_path),
            middleware=[
                *self._middleware(), SkillCreationGuard(),
                FilesystemMiddleware(backend=backend,
                                     tools=["ls", "read_file", "write_file", "edit_file", "glob", "grep"],
                                     _permissions=permissions),
            ],
            backend=backend,
            permissions=permissions,
            skills=["/skills/"],
            memory=[],
            checkpointer=self.checkpointer,
            name=self.agent_name,
            debug=self.config.debug,
        )
