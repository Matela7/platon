"""Application logging helpers shared by Platon modules."""

from __future__ import annotations

import inspect
import logging
import os
from functools import wraps
from time import perf_counter
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

LOGGER = logging.getLogger("platon")


class _ColorFormatter(logging.Formatter):
    """Colorize only the level name when writing to a terminal."""

    _LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",     # cyan
        logging.INFO: "\033[32m",      # green
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    _RESET = "\033[0m"

    def __init__(self, *args: Any, color: bool, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        if not self.color:
            return super().format(record)

        # Formatting works on a copy so other handlers see the original record.
        colored_record = logging.makeLogRecord(record.__dict__.copy())
        color = self._LEVEL_COLORS.get(record.levelno)
        if color:
            colored_record.levelname = f"{color}{record.levelname}{self._RESET}"
        return super().format(colored_record)


def configure_logging() -> logging.Logger:
    """Configure timestamped console logging once for the application."""
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        use_color = handler.stream.isatty() and "NO_COLOR" not in os.environ
        handler.setFormatter(_ColorFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            color=use_color,
        ))
        LOGGER.addHandler(handler)
        LOGGER.propagate = False

    level_name = os.getenv("PLATON_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO
    LOGGER.setLevel(level)
    return LOGGER


configure_logging()


def log_call(func: F) -> F:
    """Log function lifecycle and elapsed time without logging its arguments."""
    name = f"{func.__module__}.{func.__qualname__}"

    def started() -> float:
        LOGGER.info("Start: %s", name)
        return perf_counter()

    def succeeded(start: float) -> None:
        LOGGER.info("Done: %s (%.3fs)", name, perf_counter() - start)

    def failed(start: float, exc: BaseException) -> None:
        LOGGER.error("Failed: %s after %.3fs (exception=%s)", name, perf_counter() - start, type(exc).__name__)

    if inspect.isasyncgenfunction(func):
        @wraps(func)
        async def async_generator_wrapper(*args: Any, **kwargs: Any):
            start = started()
            try:
                async for item in func(*args, **kwargs):
                    yield item
            except Exception as exc:
                failed(start, exc)
                raise
            else:
                succeeded(start)
        return async_generator_wrapper  # type: ignore[return-value]

    if inspect.isgeneratorfunction(func):
        @wraps(func)
        def generator_wrapper(*args: Any, **kwargs: Any):
            start = started()
            try:
                yield from func(*args, **kwargs)
            except Exception as exc:
                failed(start, exc)
                raise
            else:
                succeeded(start)
        return generator_wrapper  # type: ignore[return-value]

    if inspect.iscoroutinefunction(func):
        @wraps(func)
        async def coroutine_wrapper(*args: Any, **kwargs: Any):
            start = started()
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                failed(start, exc)
                raise
            succeeded(start)
            return result
        return coroutine_wrapper  # type: ignore[return-value]

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        start = started()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            failed(start, exc)
            raise
        succeeded(start)
        return result
    return wrapper  # type: ignore[return-value]
