"""Bound model context without deleting checkpoint history or splitting tool calls."""

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import BaseMessage, HumanMessage


def bounded_messages(messages: list[BaseMessage], limit: int) -> list[BaseMessage]:
    starts = [i for i, message in enumerate(messages) if isinstance(message, HumanMessage)]
    if not starts:
        return messages
    # Keep the entire active turn. Completed turns are added only when they fit.
    start = starts[-1]
    for earlier in reversed(starts[:-1]):
        if len(messages) - earlier > limit:
            break
        start = earlier
    return messages[start:]


def context_middleware(limit: int):
    @wrap_model_call
    def trim_context(request, handler):
        return handler(request.override(messages=bounded_messages(request.messages, limit)))

    return trim_context
