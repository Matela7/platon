from __future__ import annotations

from pathlib import Path

from app_logging import LOGGER, log_call

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@log_call
def load_prompt(filename: str) -> str:
    """Load a prompt file from the local prompts directory.

    Args:
        filename: Prompt file name, for example ``agent_prompt.md``.

    Returns:
        Prompt text with surrounding whitespace removed.
    """
    prompt_path = PROMPTS_DIR / filename
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    LOGGER.info("Prompt loaded (%s)", prompt_path.name)
    return prompt
