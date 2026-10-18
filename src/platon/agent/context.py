"""Bound model context without deleting checkpoint history or splitting tool calls."""

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


# Leave room in Ollama's 16k-token window for the system prompt, tool schemas,
# tokenizer variance in OCR text, and the next model response.
MAX_CONTEXT_CHARS = 20_000


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = f"\n[... {len(value) - limit} characters omitted to fit the model context ...]\n"
    head = max(0, (limit - len(marker)) * 2 // 3)
    tail = max(0, limit - len(marker) - head)
    return value[:head] + marker + (value[-tail:] if tail else "")


def _message_size(message: BaseMessage) -> int:
    # Tool-call arguments are part of the model input even when content is empty.
    return len(str(message.content)) + len(str(getattr(message, "tool_calls", ""))) + 100


def bounded_messages(messages: list[BaseMessage], limit: int, max_chars: int = MAX_CONTEXT_CHARS) -> list[BaseMessage]:
    starts = [i for i, message in enumerate(messages) if isinstance(message, HumanMessage)]
    if not starts:
        return messages
    # Keep the entire active turn. Completed turns are added only when they fit.
    start = starts[-1]
    for earlier in reversed(starts[:-1]):
        if len(messages) - earlier > limit or sum(map(_message_size, messages[earlier:])) > max_chars:
            break
        start = earlier
    selected = list(messages[start:])
    if sum(map(_message_size, selected)) <= max_chars:
        return selected

    # Preserve every call/result pair in the active turn. Compact oversized tool
    # outputs in the model view only; checkpoint history retains original messages.
    tool_count = sum(isinstance(message, ToolMessage) for message in selected)
    tool_allowance = max(250, min(4_000, max_chars // max(1, tool_count * 2)))
    for index, message in enumerate(selected):
        if isinstance(message, ToolMessage) and isinstance(message.content, str):
            selected[index] = message.model_copy(update={"content": _shorten(message.content, tool_allowance)})
    if sum(map(_message_size, selected)) <= max_chars:
        return selected

    # The latest user request and outstanding call arguments also count toward
    # Ollama's limit. Keep their beginning and end when one is unusually large.
    for index, message in enumerate(selected):
        if isinstance(message.content, str) and not isinstance(message, ToolMessage):
            allowance = 8_000 if isinstance(message, HumanMessage) else 2_000
            selected[index] = message.model_copy(update={"content": _shorten(message.content, allowance)})
    if sum(map(_message_size, selected)) > max_chars:
        # Large tool-call arguments or many short pairs can still exceed the
        # budget. Keep the newest exchanges and always retain the user request.
        while len(selected) > 1 and sum(map(_message_size, selected)) > max_chars:
            if isinstance(selected[1], AIMessage) and selected[1].tool_calls:
                call_ids = {call.get("id") for call in selected[1].tool_calls}
                end = 2
                while end < len(selected) and isinstance(selected[end], ToolMessage) and selected[end].tool_call_id in call_ids:
                    end += 1
                del selected[1:end]
            else:
                del selected[1]
    return selected


def context_middleware(limit: int, num_ctx: int = 16_384):
    # Approximate two characters per token for noisy OCR and reserve 6k tokens
    # for system instructions, tool schemas and the model's response.
    char_budget = max(2_000, (num_ctx - 6_000) * 2)

    @wrap_model_call
    def trim_context(request, handler):
        return handler(request.override(messages=bounded_messages(request.messages, limit, char_budget)))

    return trim_context
