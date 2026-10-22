"""A conversation-bound wrapper over the supervisor's runnable."""

from collections.abc import Iterator
from pathlib import Path
from threading import Event
from time import perf_counter
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command, Overwrite
from langgraph.graph import END

from platon.app_logging import LOGGER, log_call
from platon.agent.agents.supervisor_agent import SupervisorAgent
from platon.agent.base_agent import BaseAgent
from platon.agent.cancellation import RunStopped, StopHandler
from platon.agent.conversation_store import ConversationStore
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from platon.agent.results import content_text, current_turn, execution_report, visible_messages

MessageHistory = list[dict[str, str]]
def _duration_seconds(value: object) -> float:
    """Convert optional Ollama nanosecond metadata to seconds."""
    return value / 1e9 if isinstance(value, (int, float)) else 0.0


class AgentOrchestrator:
    @log_call
    def __init__(self, config=None, agent_config=None, agent: BaseAgent | None = None, thread_id=None):
        self.config = config or AgentOrchestratorConfig()
        self.agent_config = agent_config or (agent.config if agent else AgentConfig())
        self.store = ConversationStore(Path(self.config.sqlite_path or self.config.working_dir / "agent_threads.sqlite3"))
        self.thread_id = thread_id or self.store.latest() or str(uuid4())
        self.store.ensure(self.thread_id)
        self.agent = agent or SupervisorAgent.from_config(self.agent_config, self.config, checkpointer=self.store.checkpointer)
        if not isinstance(self.agent, BaseAgent):
            self.store.close()
            raise TypeError("agent must inherit from BaseAgent")
        if self.agent.checkpointer is None:
            if "runnable" in self.agent.__dict__:
                self.store.close()
                raise ValueError("Set the checkpointer before the agent's first execution.")
            self.agent.checkpointer = self.store.checkpointer
        self.checkpointer = self.agent.checkpointer
        self.graph = self.agent.runnable
        self._running = Event()
        self._stop_event = Event()
        # Sync streaming reserves a worker for its event waiter, so it needs at least two.
        self.run_config = {"configurable": {"thread_id": f"platon-chat-v2:{self.thread_id}"}, "max_concurrency": 2, "recursion_limit": 100}
        LOGGER.info("Conversation ready (agent=%s)", self.agent.agent_name)

    def _snapshot(self):
        return self.graph.get_state(self.run_config)

    def pending_interrupts(self):
        return [{"id": item.id, "value": item.value} for item in self._snapshot().interrupts]

    def can_retry(self):
        snapshot = self._snapshot()
        return bool(snapshot.next) and not snapshot.interrupts

    def load_thread_history(self):
        return self.store.load(self.thread_id)

    def list_threads(self):
        return self.store.list()

    def thread_exists(self, thread_id):
        return self.store.exists(thread_id)

    def close(self):
        try:
            close = getattr(self.agent, "close", None)
            if close is not None:
                close()
        finally:
            self.store.close()

    def stop(self) -> bool:
        """Request cancellation from another thread; the runner performs cleanup."""
        if not self._running.is_set():
            return False
        self._stop_event.set()
        LOGGER.info("Conversation stop requested")
        return True

    @log_call
    def stream(self, user_input: str, history: MessageHistory | None = None, *, stop_event: Event | None = None) -> Iterator[dict[str, Any]]:
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("Message cannot be empty.")
        snapshot = self._snapshot()
        if snapshot.interrupts:
            raise ValueError("Resolve the pending approval or question first.")
        if snapshot.next:
            raise ValueError("Continue the unfinished run before sending a new message.")
        visible = list(history if history is not None else self.load_thread_history())
        # Bootstrap older conversations once; checkpoints remain the execution source of truth.
        messages = [] if snapshot.values else [
            (HumanMessage if item["role"] == "user" else AIMessage)(content=item["content"])
            for item in visible if item.get("role") in {"user", "assistant"}
        ]
        messages.append(HumanMessage(content=user_input.strip(), id=str(uuid4())))
        visible.append({"role": "user", "content": user_input.strip()})
        self.store.save(self.thread_id, visible)
        LOGGER.info("Conversation input persisted; starting agent workflow")
        yield from self._run({"messages": messages}, stop_event=stop_event)

    @staticmethod
    def _result(events):
        result = None
        for event in events:
            if event["type"] == "result":
                result = event["data"]
        if result is None:
            raise RuntimeError("The agent run ended without a result.")
        return result

    def invoke(self, user_input: str, history: MessageHistory | None = None):
        return self._result(self.stream(user_input, history))

    @log_call
    def resume_stream(self, decisions, *, stop_event: Event | None = None):
        pending = self.pending_interrupts()
        if not pending or not isinstance(decisions, dict) or set(decisions) != {item["id"] for item in pending}:
            raise ValueError("Responses must match the pending interrupt ids.")
        for item in pending:
            response = decisions[item["id"]]
            if item["value"].get("kind") == "clarification":
                if not isinstance(response, dict) or not isinstance(response.get("answer"), str) or not response["answer"].strip():
                    raise ValueError("Provide a nonempty answer to the question.")
            else:
                choices = response.get("decisions") if isinstance(response, dict) else None
                if not isinstance(choices, list) or len(choices) != len(item["value"]["action_requests"]):
                    raise ValueError("Provide one decision for each proposed action.")
                if any(not isinstance(c, dict) or c.get("type") not in {"approve", "reject"} or ("message" in c and not isinstance(c["message"], str)) for c in choices):
                    raise ValueError("Decision type must be approve or reject; feedback must be text.")
        LOGGER.info("Resuming workflow with %d decision(s)", len(pending))
        yield from self._run(Command(resume=decisions), stop_event=stop_event)

    def resume(self, decisions):
        return self._result(self.resume_stream(decisions))

    @log_call
    def retry_stream(self, *, stop_event: Event | None = None):
        if not self.can_retry():
            raise ValueError("There is no unfinished run to continue.")
        # Resume from the failed node; do not append another user message or replay completed tools.
        LOGGER.info("Retrying unfinished workflow from its checkpoint")
        yield from self._run(None, stop_event=stop_event)

    def _finish_stopped(self, messages, partial_text):
        """Close pending tool pairs and discard scheduled work, retaining evidence."""
        messages = list(messages)
        answered = {message.tool_call_id for message in messages if isinstance(message, ToolMessage)}
        for message in list(messages):
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    if call["id"] not in answered:
                        messages.append(ToolMessage(
                            content="Stopped by user before a result was recorded.",
                            tool_call_id=call["id"], name=call["name"], status="error",
                        ))
        if not messages or not isinstance(messages[-1], AIMessage) or messages[-1].tool_calls:
            text = partial_text.strip()
            messages.append(AIMessage(content=(text + "\n\n" if text else "") + "[⏹]"))
        self.graph.update_state(self.run_config, {"messages": Overwrite(messages)}, as_node="model")
        self.graph.update_state(self.run_config, None, as_node=END)
        return self._snapshot()

    def discard_pending_run(self) -> bool:
        """Cancel an interrupted or failed run so a new user turn can start."""
        if self._running.is_set():
            raise RuntimeError("Stop the active run before discarding pending work.")
        snapshot = self._snapshot()
        if not snapshot.next and not snapshot.interrupts:
            return False
        snapshot = self._finish_stopped(snapshot.values.get("messages", []), "")
        self.store.save(self.thread_id, visible_messages(snapshot.values.get("messages", [])))
        return True

    @log_call
    def _run(self, graph_input, *, stop_event: Event | None = None):
        if self._running.is_set():
            raise RuntimeError("An agent run is already active.")
        active_stop_event = stop_event or Event()
        self._stop_event = active_stop_event
        self._running.set()
        try:
            yield from self._run_active(graph_input, active_stop_event)
        finally:
            self._running.clear()

    def _run_active(self, graph_input, stop_event: Event):
        started = perf_counter()
        run_id = str(uuid4())
        result = {}
        error = None
        stopped = False
        partial_text = ""
        LOGGER.info("Agent workflow started (run_id=%s)", run_id)
        stop_handler = StopHandler(stop_event)
        try:
            for namespace, mode, chunk in self.graph.stream(
                graph_input, config={**self.run_config, "run_name": "supervisor", "metadata": {"agent": self.agent.agent_name},
                                     "callbacks": [stop_handler]},
                stream_mode=["values", "messages", "updates"], subgraphs=True,
            ):
                stop_handler.check()
                if mode == "values" and not namespace:
                    result = chunk
                elif mode == "messages" and not namespace:
                    message, metadata = chunk
                    text = message.content if isinstance(message.content, str) else content_text(message.content)
                    if isinstance(message, AIMessage) and not message.tool_calls and text:
                        partial_text += text
                        yield {"type": "delta", "data": text}
                elif mode == "updates" and isinstance(chunk, dict):
                    for update in chunk.values():
                        if not isinstance(update, dict):
                            continue
                        messages = update.get("messages", [])
                        if isinstance(messages, Overwrite):
                            # DeepAgent normalizes existing history; these are not new tool results.
                            continue
                        for message in messages:
                            if isinstance(message, ToolMessage):
                                status = message.artifact.get("status", message.status) if isinstance(message.artifact, dict) else message.status
                                LOGGER.info("Tool step completed (tool=%s, status=%s)", message.name, status)
                                yield {"type": "progress", "data": {"tool": message.name, "status": status}}
        except RunStopped:
            stopped = True
            LOGGER.info("Agent workflow stopped by request (run_id=%s)", run_id)
            snapshot = self._snapshot()
            messages = snapshot.values.get("messages", result.get("messages", []))
            if isinstance(graph_input, dict) and graph_input.get("messages"):
                incoming = graph_input["messages"][-1]
                if not snapshot.values:
                    messages = graph_input["messages"]
                elif incoming.id and not any(message.id == incoming.id for message in messages):
                    messages = [*messages, incoming]
            snapshot = self._finish_stopped(messages, partial_text)
            result = {**result, "messages": snapshot.values.get("messages", messages)}
        except Exception as exc:
            error = exc
            LOGGER.exception("Agent workflow failed (run_id=%s)", run_id)
        snapshot = self._snapshot()
        messages = snapshot.values.get("messages", result.get("messages", []))
        for message in reversed(current_turn(messages)):
            if isinstance(message, AIMessage) and message.response_metadata.get("total_duration"):
                metadata = message.response_metadata
                LOGGER.info(
                    "Ollama timing (load=%.3fs, prompt=%.3fs, generation=%.3fs, output_tokens=%s)",
                    _duration_seconds(metadata.get("load_duration")),
                    _duration_seconds(metadata.get("prompt_eval_duration")),
                    _duration_seconds(metadata.get("eval_duration")),
                    metadata.get("eval_count", 0),
                )
                break
        interrupts = [{"id": item.id, "value": item.value} for item in snapshot.interrupts]
        report = execution_report(messages, error)
        if stopped:
            report.update(status="stopped", answer="", errors=[])
        if interrupts:
            LOGGER.info("Agent workflow paused for %d pending decision(s)", len(interrupts))
            report.update(status="interrupted", answer="", errors=[])
        # On errors, checkpoint messages retain confirmed work. Visible history is reconciled too.
        persisted = visible_messages(messages)
        if persisted:
            self.store.save(self.thread_id, persisted)
        payload = {**report, "run_id": run_id, "thread_id": self.thread_id, "interrupts": interrupts,
                   "can_retry": bool(snapshot.next) and not interrupts, "result": result,
                   "elapsed_seconds": round(perf_counter() - started, 3)}
        LOGGER.info("Agent workflow finished (run_id=%s, status=%s, elapsed=%.3fs)", run_id, payload["status"], payload["elapsed_seconds"])
        yield {"type": "result", "data": payload}
