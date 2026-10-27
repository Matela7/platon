from collections.abc import Iterator
from threading import Event
from typing import Any

from platon.app_logging import LOGGER, log_call
from platon.agent.agent_orchestrator import AgentOrchestrator
from platon.agent.base_agent import BaseAgent
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import (
    AgentOrchestratorConfig,
)

RuntimeEvent = dict[str, Any]
MessageHistory = list[dict[str, str]]


class AgentRuntimeService:
    """Expose the agent runtime operations for a single conversation."""

    @log_call
    def __init__(
        self,
        orchestrator_config: AgentOrchestratorConfig,
        agent_config: AgentConfig,
        agent: BaseAgent | None = None,
        thread_id: str | None = None,
    ):
        self._orchestrator = self._create_agent_runtime(
            orchestrator_config=orchestrator_config,
            agent_config=agent_config,
            agent=agent,
            thread_id=thread_id,
        )
        self._closed = False

    @staticmethod
    @log_call
    def _create_agent_runtime(
        orchestrator_config: AgentOrchestratorConfig,
        agent_config: AgentConfig,
        agent: BaseAgent | None = None,
        thread_id: str | None = None,
    ) -> AgentOrchestrator:
        try:
            return AgentOrchestrator(
                config=orchestrator_config,
                agent_config=agent_config,
                agent=agent,
                thread_id=thread_id,
            )
        except Exception:
            LOGGER.exception("Agent runtime initialization failed")
            raise

    @property
    def thread_id(self) -> str:
        """Return the conversation ID selected by the orchestrator."""
        return self._orchestrator.thread_id

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Agent runtime service is closed.")

    @log_call
    def stream(
        self,
        user_input: str,
        *,
        stop_event: Event | None = None,
    ) -> Iterator[RuntimeEvent]:
        """Stream a new user turn using the persisted conversation history."""
        self._ensure_open()
        try:
            yield from self._orchestrator.stream(
                user_input,
                stop_event=stop_event,
            )
        except Exception:
            LOGGER.exception("Agent runtime stream failed (thread_id=%s)", self.thread_id)
            raise

    @log_call
    def resume_stream(
        self,
        decisions: dict[str, Any],
        *,
        stop_event: Event | None = None,
    ) -> Iterator[RuntimeEvent]:
        """Resume pending approvals or clarification requests."""
        self._ensure_open()
        try:
            yield from self._orchestrator.resume_stream(
                decisions,
                stop_event=stop_event,
            )
        except Exception:
            LOGGER.exception("Agent runtime resume failed (thread_id=%s)", self.thread_id)
            raise

    @log_call
    def retry_stream(
        self,
        *,
        stop_event: Event | None = None,
    ) -> Iterator[RuntimeEvent]:
        """Continue an unfinished run from its checkpoint."""
        self._ensure_open()
        try:
            yield from self._orchestrator.retry_stream(
                stop_event=stop_event,
            )
        except Exception:
            LOGGER.exception("Agent runtime retry failed (thread_id=%s)", self.thread_id)
            raise

    @log_call
    def stop(self) -> bool:
        """Signal cancellation without waiting for the run to finish."""
        self._ensure_open()
        return self._orchestrator.stop()

    @log_call
    def discard_pending_run(self) -> bool:
        """Discard interrupted or failed work after the active run stops."""
        self._ensure_open()
        return self._orchestrator.discard_pending_run()

    @log_call
    def history(self) -> MessageHistory:
        self._ensure_open()
        return self._orchestrator.load_thread_history()

    @log_call
    def list_threads(self) -> list[dict[str, Any]]:
        self._ensure_open()
        return self._orchestrator.list_threads()

    @log_call
    def thread_exists(self, thread_id: str) -> bool:
        self._ensure_open()
        return self._orchestrator.thread_exists(thread_id)

    @log_call
    def pending_interrupts(self) -> list[dict[str, Any]]:
        self._ensure_open()
        return self._orchestrator.pending_interrupts()

    @log_call
    def can_retry(self) -> bool:
        self._ensure_open()
        return self._orchestrator.can_retry()

    @log_call
    def snapshot(self) -> dict[str, Any]:
        """Read conversation data while execution is idle or serialized."""
        self._ensure_open()
        return {
            "thread_id": self.thread_id,
            "messages": self._orchestrator.load_thread_history(),
            "interrupts": self._orchestrator.pending_interrupts(),
            "can_retry": self._orchestrator.can_retry(),
        }

    @log_call
    def get_config(self) -> dict[str, Any]:
        """Return JSON-safe configuration copies of the active runtime."""
        self._ensure_open()
        return {
            "orchestrator_config": self._orchestrator.config.model_dump(mode="json"),
            "agent_config": self._orchestrator.agent_config.model_dump(mode="json"),
        }

    @log_call
    def replace_config(
        self,
        orchestrator_config: AgentOrchestratorConfig,
        agent_config: AgentConfig,
    ) -> dict[str, Any]:
        """Rebuild an idle runtime, retaining its conversation ID.

        The caller must serialize this operation with reads and execution.
        A new configured supervisor is created; an injected agent is not reused.
        Changing the database path selects a different store without migrating data.
        """
        self._ensure_open()
        replacement = self._create_agent_runtime(
            orchestrator_config=orchestrator_config,
            agent_config=agent_config,
            thread_id=self.thread_id,
        )
        previous = self._orchestrator
        self._orchestrator = replacement
        try:
            previous.close()
        except Exception:
            # The replacement is already live; report cleanup failure in logs
            # without misleading callers into retrying a successful update.
            LOGGER.exception("Previous agent runtime cleanup failed (thread_id=%s)", self.thread_id)
        return self.get_config()

    @log_call
    def close(self) -> None:
        """Release resources after execution and other operations finish."""
        if self._closed:
            return

        try:
            self._orchestrator.close()
        except Exception:
            LOGGER.exception("Agent runtime shutdown failed (thread_id=%s)", self.thread_id)
            raise
        finally:
            self._closed = True
