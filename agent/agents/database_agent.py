"""Database agent: the only role that receives private RAG tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.base_agent import BaseAgent
from agent.models.agent_config import AgentConfig
from agent.tools.tools import create_rag_tools

if TYPE_CHECKING:
    from vectorstore.client_manager import ClientManager


class DatabaseAgent(BaseAgent):
    """Search and maintain Chroma collections on delegated requests."""

    agent_name = "database_agent"
    prompt_path = "agents/database.md"

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
        if tools_list is None:
            self.tools_list = list(create_rag_tools(client_manager))

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
