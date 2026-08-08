from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

from agent.models.agent_config import AgentConfig
from agent.prompt_loader import load_prompt
from agent.tools.errors import ToolError
from agent.tools.tools import (
    create_execution_tools,
    create_file_management_tools,
    create_http_tools,
    create_search_tools,
    create_utils_tools,
)
from vectorstore.client_manager import ClientManager


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(part.strip() for part in parts if part.strip()).strip()


def _extract_subagent_answer(result: Any, agent_name: str) -> str:
    if not isinstance(result, dict):
        raise ToolError(
            agent_name,
            "reading the subagent result",
            f"Expected a result dictionary, received {type(result).__name__}.",
        )

    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage):
            answer = _content_to_text(message.content)
            if answer:
                return answer
        elif isinstance(message, dict) and message.get("role") == "assistant":
            answer = _content_to_text(message.get("content"))
            if answer:
                return answer

    raise ToolError(
        agent_name,
        "reading the subagent result",
        "The subagent completed without a final assistant message.",
    )


def create_subagent_tools(
    model: BaseChatModel,
    cm: ClientManager,
    config: AgentConfig,
) -> list[BaseTool]:
    """Create supervisor delegation tools backed by role-specific agents."""
    search_tools = create_search_tools(cm)
    utility_tools = create_utils_tools()
    tools_by_name = {
        tool_instance.name: tool_instance
        for tool_instance in (*search_tools, *utility_tools)
    }

    research_tools = [
        tools_by_name[name]
        for name in (
            "search_collection",
            "search_all_collections",
            "get_list_of_collections",
            "add_document_to_collection",
            "search_web",
            "get_current_time",
        )
    ]
    research_tools.extend(create_http_tools(config.max_tool_output_chars))

    workspace_tools = list(
        create_file_management_tools(
            config.working_dir,
            config.max_tool_output_chars,
        )
    )
    execution_tools = list(
        create_execution_tools(
            config.working_dir,
            config.max_tool_output_chars,
        )
    )

    research_agent = create_agent(
        model=model,
        tools=research_tools,
        system_prompt=load_prompt(config.research_prompt),
        name="research_subagent",
    )
    workspace_agent = create_agent(
        model=model,
        tools=workspace_tools,
        system_prompt=load_prompt(config.workspace_prompt).format(
            workspace_root=config.working_dir.expanduser().resolve()
        ),
        name="workspace_subagent",
    )
    execution_agent = create_agent(
        model=model,
        tools=execution_tools,
        system_prompt=load_prompt(config.execution_prompt).format(
            workspace_root=config.working_dir.expanduser().resolve()
        ),
        name="execution_subagent",
    )

    def invoke_subagent(agent: Any, agent_name: str, task: str) -> str:
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": task}]},
                config={
                    "run_name": agent_name,
                    "tags": ["platon", "subagent", agent_name],
                    "metadata": {
                        "agent": agent_name,
                        "tool": f"delegate_{agent_name.removesuffix('_subagent').split('_')[-1]}",
                    },
                },
            )
            return _extract_subagent_answer(result, agent_name)
        except Exception as exc:
            raise ToolError.from_exception(
                agent_name,
                f"delegating task '{task}'",
                exc,
            ) from exc

    @tool("delegate_research")
    def delegate_research(task: str) -> str:
        """Delegate document, web, API, or knowledge-base research."""
        return invoke_subagent(research_agent, "research_subagent", task)

    @tool("delegate_workspace")
    def delegate_workspace(task: str) -> str:
        """Delegate scoped file reading, writing, copying, moving, or deletion."""
        return invoke_subagent(workspace_agent, "workspace_subagent", task)

    @tool("delegate_execution")
    def delegate_execution(task: str) -> str:
        """Delegate host shell commands, Python code, and data computation."""
        return invoke_subagent(execution_agent, "execution_subagent", task)

    delegation_tools = [
        delegate_research,
        delegate_workspace,
        delegate_execution,
    ]
    for tool_instance in delegation_tools:
        tool_instance.handle_tool_error = True
        tool_instance.handle_validation_error = (
            lambda exc, name=tool_instance.name: (
                f"Tool '{name}' received invalid arguments: {exc}"
            )
        )
    return delegation_tools
