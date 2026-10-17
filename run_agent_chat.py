#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import sys
from typing import Any

from app_logging import LOGGER, configure_logging, log_call

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

load_dotenv()
configure_logging()

from agent.agent_orchestrator import AgentOrchestrator
from agent.models.agent_config import AgentConfig
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig


@log_call
def _build_agent() -> AgentOrchestrator:
    defaults = AgentConfig()
    orchestrator_config = AgentOrchestratorConfig(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"),
        sqlite_path=os.getenv("AGENT_SQLITE_PATH"),
    )
    agent_config = AgentConfig(
        model_name=os.getenv("OLLAMA_MODEL", defaults.model_name),
        num_ctx=int(os.getenv("OLLAMA_NUM_CTX", str(defaults.num_ctx))),
        system_prompt=os.getenv("AGENT_SYSTEM_PROMPT", defaults.system_prompt),
        max_history_messages=int(
            os.getenv(
                "AGENT_MAX_HISTORY_MESSAGES",
                str(defaults.max_history_messages),
            )
        ),
    )
    return AgentOrchestrator(
        config=orchestrator_config,
        agent_config=agent_config,
    )


@log_call
def _review_pending(agent: AgentOrchestrator, payload: dict[str, Any]) -> dict[str, Any]:
    """Review persisted actions one by one, then resume the same graph thread."""
    while payload.get("interrupts"):
        decisions = {}
        for review in payload["interrupts"]:
            if review["value"].get("kind") == "clarification":
                answer = ""
                while not answer:
                    answer = input(f"\n{review['value']['question']} ").strip()
                decisions[review["id"]] = {"answer": answer}
                continue
            choices = []
            for action in review["value"]["action_requests"]:
                print(f"\nDo zatwierdzenia: {action.get('description', action['name'])}")
                print(json.dumps(action["args"], ensure_ascii=False, indent=2))
                while True:
                    choice = input("Zatwierdzic? [t/n]: ").strip().lower()
                    if choice in {"t", "n"}:
                        break
                choices.append({"type": "approve" if choice == "t" else "reject"})
            decisions[review["id"]] = {"decisions": choices}
        payload = agent.resume(decisions)
    return payload


@log_call
def main() -> int:
    try:
        LOGGER.info("Starting terminal chat application")
        agent = _build_agent()
    except Exception as exc:
        LOGGER.error("Terminal chat initialization failed (exception=%s)", type(exc).__name__)
        print(f"Init error: {exc}", file=sys.stderr)
        return 1

    print("Agent chat uruchomiony (supervisor + delegowani specjalisci).")
    print("Wpisz 'exit', 'quit' albo 'wyjdz', aby zakonczyc.")
    history = agent.load_thread_history()

    while True:
        try:
            pending = agent.pending_interrupts()
            if pending:
                payload = _review_pending(agent, {"interrupts": pending})
                print(f"Agent: {payload['answer'] or payload['errors']}")
                if payload['answer'] and payload.get('errors'):
                    print("Nieukonczone elementy:", json.dumps(payload["errors"], ensure_ascii=False))
                history = agent.load_thread_history()
            if agent.can_retry():
                if input("Kontynuowac niedokonczone wykonanie? [t/n]: ").strip().lower() != "t":
                    agent.close()
                    return 0
                payload = agent._result(agent.retry_stream())
                payload = _review_pending(agent, payload)
                print(f"Agent: {payload['answer'] or payload['errors']}")
                continue
            user_input = input("\nTy: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nKoniec.")
            agent.close()
            return 0

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "q", "wyjdz", "koniec"}:
            print("Koniec.")
            agent.close()
            return 0

        try:
            payload = agent.invoke(user_input=user_input, history=history)
            payload = _review_pending(agent, payload)
        except (KeyboardInterrupt, EOFError):
            print("\nZapisano oczekujaca decyzje. Koniec.")
            agent.close()
            return 0
        except Exception as exc:
            LOGGER.error("Terminal chat request failed (exception=%s)", type(exc).__name__)
            text = str(exc)
            if "Errno 8" in text or "nodename nor servname provided" in text:
                print(
                    "\nAgent: Blad sieci (DNS). Sprawdz Internet/VPN/proxy "
                    "i czy host API jest osiagalny."
                )
            else:
                print(f"\nAgent: Blad podczas zapytania: {exc}")
            continue

        print(f"Agent: {payload['answer']}")
        if payload.get("errors"):
            print("Nieukonczone elementy:", json.dumps(payload["errors"], ensure_ascii=False))

        history = agent.load_thread_history()


if __name__ == "__main__":
    raise SystemExit(main())
