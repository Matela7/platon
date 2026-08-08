#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

load_dotenv()

from agent.base_agent import BaseAgent
from agent.models.agent_config import AgentConfig


def _extract_last_assistant_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
        else:
            message_type = getattr(message, "type", None)
            if message_type != "ai":
                continue

        if isinstance(content, str):
            text = content.strip()
            if text:
                return text

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            merged = "\n".join(part.strip() for part in parts if part and part.strip()).strip()
            if merged:
                return merged

    return "Nie udalo sie odczytac odpowiedzi modelu."


def _build_agent() -> BaseAgent:
    config = AgentConfig(
        model_name=os.getenv("OLLAMA_MODEL", AgentConfig().model_name),
        base_url=os.getenv("OLLAMA_BASE_URL", AgentConfig().base_url),
        persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"),
        system_prompt=os.getenv("AGENT_SYSTEM_PROMPT", AgentConfig().system_prompt),
        sqlite_path=os.getenv("AGENT_SQLITE_PATH"),
        max_history_messages=int(
            os.getenv(
                "AGENT_MAX_HISTORY_MESSAGES",
                str(AgentConfig().max_history_messages),
            )
        ),
    )
    return BaseAgent(config=config)


def main() -> int:
    try:
        agent = _build_agent()
    except Exception as exc:
        print(f"Init error: {exc}", file=sys.stderr)
        return 1

    print("Agent chat uruchomiony (base agent bez routera).")
    print("Wpisz 'exit', 'quit' albo 'wyjdz', aby zakonczyc.")
    history: list[dict[str, str]] = []

    while True:
        try:
            user_input = input("\nTy: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nKoniec.")
            return 0

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "q", "wyjdz", "koniec"}:
            print("Koniec.")
            return 0

        try:
            payload = agent.invoke(user_input=user_input, history=history)
        except Exception as exc:
            text = str(exc)
            if "Errno 8" in text or "nodename nor servname provided" in text:
                print(
                    "\nAgent: Blad sieci (DNS). Sprawdz Internet/VPN/proxy "
                    "i czy host API jest osiagalny."
                )
            else:
                print(f"\nAgent: Blad podczas zapytania: {exc}")
            continue

        result = payload.get("result", {})
        result_messages = result.get("messages", [])
        assistant_text = payload.get("answer") or _extract_last_assistant_text(result_messages)
        print(f"Agent: {assistant_text}")

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": assistant_text})


if __name__ == "__main__":
    raise SystemExit(main())
