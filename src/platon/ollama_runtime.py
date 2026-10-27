"""Start and verify the local Ollama service before building an agent."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from platon.app_logging import LOGGER


def _is_reachable(base_url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/api/version",
            timeout=timeout,
        ) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def ensure_local_ollama(
    base_url: str | None = None,
    *,
    timeout_seconds: float = 30.0,
) -> None:
    """Ensure a local Ollama endpoint is reachable.

    Remote endpoints are only checked, never started. A clear error is raised
    when a local service cannot be started or does not become ready.
    """
    url = base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    if _is_reachable(url):
        return

    host = urlparse(url).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"Ollama is not reachable at configured remote URL: {url}")

    executable = shutil.which("ollama")
    if executable is None:
        raise RuntimeError(
            "Ollama is not reachable and the 'ollama' executable is not on PATH. "
            "Install Ollama or start it before launching Platon."
        )

    try:
        subprocess.Popen(
            (executable, "serve"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start Ollama: {exc}") from exc

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _is_reachable(url):
            LOGGER.info("Ollama is ready at %s", url)
            return
        time.sleep(0.25)
    raise RuntimeError(
        f"Ollama did not become ready at {url} within {timeout_seconds:.0f} seconds."
    )
