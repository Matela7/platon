#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False


def _load_copy_base_agent_class():
    module_path = Path(__file__).resolve().parent / "agent" / "base_agent_class copy.py"
    spec = importlib.util.spec_from_file_location("base_agent_class_copy", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load BaseAgent from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BaseAgent


BaseAgent = _load_copy_base_agent_class()


class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"


def _color(text: str, *styles: str) -> str:
    if os.getenv("NO_COLOR"):
        return text
    return f"{''.join(styles)}{text}{Color.RESET}"


def _build_agent() -> BaseAgent:
    load_dotenv()
    model_name = os.getenv("OLLAMA_MODEL", "SpeakLeash/bielik-minitron-7B-v3.0-instruct:Q4_K_M")
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")
    return BaseAgent(model_name=model_name, persist_dir=persist_dir)


def main() -> int:
    try:
        agent = _build_agent()
    except Exception as exc:
        print(_color(f"Init error: {exc}", Color.RED, Color.BOLD), file=sys.stderr)
        return 1

    print(_color("Agent chat uruchomiony (copy flow bez routera).", Color.GREEN, Color.BOLD))
    print(_color("Wpisz 'exit', 'quit' albo 'wyjdz', aby zakonczyc.", Color.DIM))
    history: list[dict[str, str]] = []

    while True:
        try:
            user_input = input(_color("\nTy: ", Color.CYAN, Color.BOLD)).strip()
        except (KeyboardInterrupt, EOFError):
            print(_color("\nKoniec.", Color.YELLOW))
            return 0

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "q", "wyjdz", "koniec"}:
            print(_color("Koniec.", Color.YELLOW))
            return 0

        try:
            payload = agent.invoke(user_input=user_input, history=history)
        except Exception as exc:
            text = str(exc)
            if "Errno 8" in text or "nodename nor servname provided" in text:
                print(
                    _color(
                        "\nAgent: Blad sieci (DNS). Sprawdz Internet/VPN/proxy "
                        "i czy host API jest osiagalny.",
                        Color.RED,
                        Color.BOLD,
                    )
                )
            else:
                print(_color(f"\nAgent: Blad podczas zapytania: {exc}", Color.RED, Color.BOLD))
            continue

        assistant_text = payload.get("answer") or "Nie udalo sie odczytac odpowiedzi modelu."
        print(_color("\nAgent: ", Color.GREEN, Color.BOLD) + assistant_text)

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": assistant_text})


if __name__ == "__main__":
    raise SystemExit(main())
