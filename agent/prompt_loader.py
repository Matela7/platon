from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(filename: str) -> str:
    """Load a prompt file from the local prompts directory.

    Args:
        filename: Prompt file name, for example ``agent_prompt.md``.

    Returns:
        Prompt text with surrounding whitespace removed.
    """
    prompt_path = PROMPTS_DIR / filename
    return prompt_path.read_text(encoding="utf-8").strip()