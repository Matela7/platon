"""Minimal technical base shared by every concrete agent."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from functools import cached_property
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.types import Command, StreamMode
from langgraph.errors import GraphBubbleUp

from platon.app_logging import LOGGER, log_call
from platon.agent.models.agent_config import AgentConfig
from platon.agent.context import context_middleware
from platon.agent.prompt_loader import load_prompt


class BaseAgent:
    """Hold a model, a prompt and tools, and compile a LangChain agent.

    Role-specific dependencies belong to subclasses. In particular this class
    knows nothing about Chroma, RAG, workspaces, or delegation.
    """

    agent_name = "base_agent"
    prompt_path: str | None = None
    delegation_description = "Delegate a bounded task to this specialist."

    def __init__(
        self,
        model: BaseChatModel,
        config: AgentConfig | None = None,
        tools_list: list[BaseTool] | None = None,
        prompt: str | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.model = model
        self.tools_list = list(tools_list or [])
        self.prompt = prompt
        self.checkpointer = checkpointer

    @property
    def model_name(self) -> str:
        """Return a stable model label for tracing metadata."""
        for attribute in ("model", "model_name"):
            value = getattr(self.model, attribute, None)
            if isinstance(value, str) and value:
                return value
        return type(self.model).__name__

    @cached_property
    def runnable(self) -> Any:
        """Create the runnable once, on first use."""
        return self.create_agent()

    def _default_prompt(self) -> str:
        """Load the prompt declared by the concrete agent class."""
        if self.prompt_path is None:
            raise NotImplementedError(
                f"{type(self).__name__} must define prompt_path or receive prompt"
            )
        return load_prompt(self.prompt_path)

    @staticmethod
    def _input(
        task: str | Command, context_messages: Sequence[BaseMessage] | None,
    ) -> dict[str, Any] | Command:
        if isinstance(task, Command):
            return task
        if not task.strip():
            raise ValueError("task must not be empty")
        messages = [
            message
            for message in context_messages or []
            if not isinstance(message, SystemMessage)
        ]
        messages.append(HumanMessage(content=task))
        return {"messages": messages}

    def _middleware(self) -> list[Any]:
        return [context_middleware(self.config.max_history_messages, self.config.num_ctx)]

    @log_call
    def create_agent(self) -> Any:
        """Create this role's LangChain agent."""
        LOGGER.info("Compiling agent workflow (agent=%s, tools=%d)", self.agent_name, len(self.tools_list))
        return create_agent(
            model=self.model,
            tools=self.tools_list,
            system_prompt=self.prompt or self._default_prompt(),
            middleware=self._middleware(),
            checkpointer=self.checkpointer,
            name=self.agent_name,
            debug=self.config.debug,
        )

    @log_call
    def invoke(
        self,
        task: str | Command,
        *,
        context_messages: Sequence[BaseMessage] | None = None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        """Run a task with optional prior conversation supplied by an adapter."""
        agent_input = self._input(task, context_messages)
        result = agent_input if isinstance(agent_input, dict) else {}
        LOGGER.info("Agent execution started (agent=%s, model=%s)", self.agent_name, self.model_name)
        try:
            for result in self.runnable.stream(agent_input, config=config, stream_mode="values"):
                pass
        except GraphBubbleUp:
            raise
        except Exception as exc:
            exc.agent_messages = result.get("messages", [])
            raise
        return result

    def stream(
        self,
        task: str | Command,
        *,
        context_messages: Sequence[BaseMessage] | None = None,
        config: dict[str, Any] | None = None,
        stream_mode: StreamMode | list[StreamMode] = "updates",
        subgraphs: bool = False,
    ) -> Iterator[Any]:
        """Stream graph events; resume an interrupt with Command(resume=...)."""
        agent_input = self._input(task, context_messages)
        LOGGER.info("Agent event stream requested (agent=%s)", self.agent_name)
        return self.runnable.stream(
            agent_input, config=config, stream_mode=stream_mode, subgraphs=subgraphs,
        )
