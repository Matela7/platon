"""Cooperative cancellation of model generation and subsequent tool calls."""

from threading import Event
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables.config import ensure_config


class RunStopped(BaseException):
    """Normal cancellation control flow, like asyncio.CancelledError."""


class StopHandler(BaseCallbackHandler):
    raise_error = True

    def __init__(self, stop_event: Event):
        self.stop_event = stop_event

    def check(self) -> None:
        if self.stop_event.is_set():
            raise RunStopped()

    def on_chat_model_start(self, serialized: dict, messages: list, **kwargs: Any) -> None:
        self.check()

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        self.check()

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self.check()

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        self.check()

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        self.check()


def current_stop_event() -> Event | None:
    """Get the cancellation signal inherited by a nested model or tool call."""
    callbacks = ensure_config().get("callbacks")
    handlers = callbacks if isinstance(callbacks, list) else getattr(callbacks, "handlers", [])
    return next((handler.stop_event for handler in handlers if isinstance(handler, StopHandler)), None)
