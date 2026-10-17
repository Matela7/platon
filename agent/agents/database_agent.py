"""Database agent: the only role that receives private RAG tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.workflow_agent import WorkflowAgent
from agent.models.agent_config import AgentConfig
from agent.tools.tools import create_rag_tools

if TYPE_CHECKING:
    from vectorstore.client_manager import ClientManager


class DatabaseAgent(WorkflowAgent):
    """Search and maintain Chroma collections on delegated requests."""

    agent_name = "database_agent"
    prompt_path = "agents/database.md"
    delegation_description = (
        "Delegate private knowledge-base retrieval and document ingestion. Use this specialist to list or search "
        "collections, answer from private documents with document and page or chunk provenance, or add a named "
        "document when the user requests it. It cannot browse the public web, inspect workspace files generally, "
        "or execute commands."
    )
    read_only_tools = frozenset({
        "search_collection", "search_all_collections", "get_list_of_collections",
    })

    def __init__(
        self,
        model: BaseChatModel,
        client_manager: ClientManager,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.client_manager = client_manager
        super().__init__(
            model=model,
            config=config,
            tools_list=tools_list,
            prompt=prompt,
            checkpointer=checkpointer,
        )
        self.max_tool_calls = self.config.database_tool_limit
        if tools_list is None:
            self.tools_list = list(create_rag_tools(client_manager, self.config.max_tool_output_chars))

    @classmethod
    def from_persist_dir(
        cls,
        model: BaseChatModel,
        persist_dir: str,
        *,
        config: AgentConfig | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> DatabaseAgent:
        """Create the database role while keeping its RAG client private."""
        from vectorstore.client_manager import ClientManager

        return cls(
            model=model,
            client_manager=ClientManager(persist_dir=persist_dir),
            config=config,
            prompt=prompt,
            checkpointer=checkpointer,
        )
