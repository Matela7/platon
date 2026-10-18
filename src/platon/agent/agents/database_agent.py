"""Database agent: the only role that receives private RAG tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from platon.agent.workflow_agent import WorkflowAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.tools.file_management import create_document_discovery_tools, create_file_management_tools
from platon.agent.tools.rag import create_rag_tools

if TYPE_CHECKING:
    from platon.vectorstore.client_manager import ClientManager


class DatabaseReadState(AgentState):
    prior_search_calls: NotRequired[list[str]]


class SearchBeforeReadGuard(AgentMiddleware):
    """Require a completed successful RAG search in this invocation before raw reads."""

    state_schema = DatabaseReadState

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any]:
        return {"prior_search_calls": [
            message.tool_call_id for message in state.get("messages", [])
            if isinstance(message, ToolMessage)
        ]}

    async def abefore_agent(self, state: Any, runtime: Any) -> dict[str, Any]:
        return self.before_agent(state, runtime)

    @staticmethod
    def _denial(request: Any) -> ToolMessage | None:
        if request.tool_call.get("name") != "read_file":
            return None
        state = request.state
        prior = set(state.get("prior_search_calls", []))
        for message in state.get("messages", []):
            if (not isinstance(message, ToolMessage)
                    or message.name not in {"search_collection", "search_all_collections"}
                    or message.status == "error" or message.tool_call_id in prior):
                continue
            try:
                payload = json.loads(message.content) if isinstance(message.content, str) else message.content
            except (ValueError, TypeError):
                continue
            # The RAG tools return lists, including [] for a successful empty search.
            # Serialized errors must never unlock reading, even with a success status.
            if isinstance(payload, list):
                return None
        return ToolMessage(
            content="Run search_collection or search_all_collections successfully first in this task, then call read_file in a later tool round.",
            tool_call_id=request.tool_call["id"], name="read_file", status="error",
        )

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        denial = self._denial(request)
        return denial if denial is not None else handler(request)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        denial = self._denial(request)
        return denial if denial is not None else await handler(request)


class DatabaseAgent(WorkflowAgent):
    """Search and maintain Chroma collections on delegated requests."""

    agent_name = "database_agent"
    prompt_path = "agents/database.md"
    use_shared_filesystem = False
    delegation_description = (
        "Delegate all document-content analysis, summaries, comparisons, quotation lookup, private knowledge-base "
        "retrieval, and document ingestion. This specialist discovers local documents with ls/glob, ingests them "
        "into a resolved collection when needed, and analyzes text retrieved through RAG with document and page "
        "or chunk provenance. After a successful RAG search it can read targeted source pages. "
        "It cannot browse the public web or execute commands."
    )
    read_only_tools = frozenset({
        "search_collection", "search_all_collections", "get_list_of_collections", "get_collection_info",
        "ls", "glob", "read_file",
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
            self.tools_list.extend(
                create_document_discovery_tools(
                    self.config.backend_root / "documents",
                    self.config.max_tool_output_chars,
                )
            )
            self.tools_list.extend(
                tool for tool in create_file_management_tools(
                    self.config.backend_root / "documents", self.config.max_tool_output_chars,
                )
                if tool.name == "read_file"
            )

    def _middleware(self) -> list[Any]:
        return [SearchBeforeReadGuard(), *super()._middleware()]

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
        from platon.vectorstore.client_manager import ClientManager

        return cls(
            model=model,
            client_manager=ClientManager(persist_dir=persist_dir),
            config=config,
            prompt=prompt,
            checkpointer=checkpointer,
        )
