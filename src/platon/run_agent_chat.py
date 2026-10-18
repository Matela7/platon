#!/usr/bin/env python3
"""Platon's interactive and script-friendly terminal client."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic
from typing import TYPE_CHECKING, Any, TextIO
from uuid import uuid4

from dotenv import load_dotenv

from platon.app_logging import LOGGER, configure_logging, log_call

load_dotenv(dotenv_path=".env")
configure_logging()

if TYPE_CHECKING:
    from platon.agent.agent_orchestrator import AgentOrchestrator


EXIT_COMMANDS = {"/exit", "/quit", "/q", "exit", "quit", "wyjdz", "koniec"}

LOGO = r""" ____  _        _  _____ ___  _   _
|  _ \| |      / \|_   _/ _ \| \ | |
| |_) | |     / _ \ | || | | |  \| |
|  __/| |___ / ___ \| || |_| | |\  |
|_|   |_____/_/   \_\_| \___/|_| \_|  CLI"""

LABRADOR = r"""       / \__
      (    @\___
      /         O
     /   (_____/
    /_____/   U
   /      \                  Labrador
  /  /     \___              Twoj kompan do pracy.
 (  /          )___
  \__\________/____)"""


PETS = {
    "labrador": (r" / \__", r"(    @\___", r"/         O", r"\ (______/"),
    "kot": (" /\\_/\\", r"( o.o )", r" > ^ <", " /   \\"),
    "lis": (" /\\   /\\", r"//\\_//\\", r"\ o   o /", r" \  V  /"),
}


@log_call
def _build_agent(thread_id: str | None = None) -> AgentOrchestrator:
    # Keep heavy model imports inside initialization so the splash appears first.
    from platon.agent.agent_orchestrator import AgentOrchestrator
    from platon.agent.models.agent_config import AgentConfig
    from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig

    defaults = AgentConfig()
    orchestrator_config = AgentOrchestratorConfig(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"),
        working_dir=os.getenv("AGENT_WORKING_DIR", str(defaults.backend_root)),
        sqlite_path=os.getenv(
            "AGENT_SQLITE_PATH",
            str(defaults.backend_root / "agent_threads.sqlite3"),
        ),
    )
    agent_config = AgentConfig(
        model_name=os.getenv("OLLAMA_MODEL", defaults.model_name),
        num_ctx=int(os.getenv("OLLAMA_NUM_CTX", str(defaults.num_ctx))),
        system_prompt=os.getenv("AGENT_SYSTEM_PROMPT", defaults.system_prompt),
        backend_root=os.getenv("AGENT_BACKEND_ROOT", str(defaults.backend_root)),
        max_history_messages=int(
            os.getenv("AGENT_MAX_HISTORY_MESSAGES", str(defaults.max_history_messages))
        ),
    )
    return AgentOrchestrator(
        config=orchestrator_config,
        agent_config=agent_config,
        thread_id=thread_id,
    )


@dataclass(frozen=True)
class Theme:
    enabled: bool

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self.paint(text, "1")

    def dim(self, text: str) -> str:
        return self.paint(text, "2")

    def cyan(self, text: str) -> str:
        return self.paint(text, "36")

    def green(self, text: str) -> str:
        return self.paint(text, "32")

    def yellow(self, text: str) -> str:
        return self.paint(text, "33")

    def red(self, text: str) -> str:
        return self.paint(text, "31")


class TerminalClient:
    """Thin presentation layer over the existing synchronous orchestrator API."""

    def __init__(
        self,
        agent: AgentOrchestrator,
        *,
        out: TextIO = sys.stdout,
        err: TextIO = sys.stderr,
        input_fn: Callable[[str], str] = input,
        color: bool | None = None,
        json_mode: bool = False,
        agent_factory: Callable[[str | None], AgentOrchestrator] = _build_agent,
    ) -> None:
        if color is None:
            color = bool(getattr(out, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ
        self.agent = agent
        self.out = out
        self.err = err
        self.input_fn = input_fn
        self.theme = Theme(color)
        self.json_mode = json_mode
        self.agent_factory = agent_factory
        self._closed = False
        self.message_queue: list[str] = []
        self.active_stop: Event | None = None
        self.last_result: dict[str, Any] | None = None
        self.steps: list[str] = []
        self.pet = "labrador"

    def request_stop(self) -> None:
        if self.active_stop is not None:
            self.active_stop.set()
        self.agent.stop()

    def observe_event(self, event: dict[str, Any]) -> None:
        if event.get("type") == "progress":
            data = event.get("data") or {}
            self.steps.append(f"{data.get('tool', 'tool')} · {data.get('status', 'done')}")
        elif event.get("type") == "result":
            self.last_result = event.get("data")

    def close(self) -> None:
        if not self._closed:
            self.agent.close()
            self._closed = True

    def _print(self, text: str = "", *, end: str = "\n", flush: bool = False) -> None:
        print(text, file=self.out, end=end, flush=flush)

    def _error(self, text: str) -> None:
        print(self.theme.red(text), file=self.err)

    def banner(self) -> None:
        width = min(shutil.get_terminal_size((72, 24)).columns, 88)
        self._print(self.theme.cyan("─" * width))
        if width >= 46:
            self._print(self.theme.cyan(LOGO))
        self._print(f"{self.theme.bold('PLATON CLI')}  {self.theme.dim('Twój lokalny asystent')}")
        self._print(self.theme.yellow(LABRADOR))
        self._print(
            f"thread {self.theme.cyan(self.agent.thread_id)} · "
            f"model {self.agent.agent_config.model_name} · /help for commands"
        )
        self._print(self.theme.cyan("─" * width))
        self._print("Napisz zadanie lub wpisz /help. Ctrl+C zatrzymuje pracę agenta.\n")

    def _read_message(self) -> str:
        """Read one message; a trailing backslash continues on the next line."""
        lines: list[str] = []
        prompt = self.theme.green("› ")
        while True:
            line = self.input_fn(prompt if not lines else self.theme.dim("… "))
            if line.endswith("\\"):
                lines.append(line[:-1])
                continue
            lines.append(line)
            return "\n".join(lines).strip()

    @staticmethod
    def _stream_worker(
        operation: Callable[[Event], Iterable[dict[str, Any]]],
        stop_event: Event,
        events: queue.Queue[tuple[str, Any]],
    ) -> None:
        try:
            for event in operation(stop_event):
                events.put(("event", event))
        except BaseException as exc:
            events.put(("error", exc))
        finally:
            events.put(("done", None))

    def run_stream(
        self, operation: Callable[[Event], Iterable[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Render events while leaving the main thread available for Ctrl+C."""
        stop_event = Event()
        self.active_stop = stop_event
        self.last_result = None
        self.steps.clear()
        events: queue.Queue[tuple[str, Any]] = queue.Queue()
        worker = Thread(
            target=self._stream_worker,
            args=(operation, stop_event, events),
            name="platon-cli-run",
            daemon=True,
        )
        worker.start()
        result: dict[str, Any] | None = None
        failure: BaseException | None = None
        answer_open = False
        saw_delta = False
        streamed_text = ""
        stop_requested = False
        done = False
        started = monotonic()
        last_tick = started
        if not self.json_mode:
            self._print(self.theme.dim("  Platon pracuje…  Ctrl+C: zatrzymaj"), flush=True)

        while not done or not events.empty():
            try:
                kind, item = events.get(timeout=0.1)
            except queue.Empty:
                now = monotonic()
                if not self.json_mode and not answer_open and now - last_tick >= 10:
                    self._print(self.theme.dim(f"  Praca w toku · {now - started:.0f}s"), flush=True)
                    last_tick = now
                continue
            except KeyboardInterrupt:
                if not stop_requested:
                    stop_requested = True
                    stop_event.set()
                    self.agent.stop()
                    if answer_open:
                        self._print()
                        answer_open = False
                    if not self.json_mode:
                        self._print(self.theme.yellow("⏹ Zatrzymywanie aktywnego zadania…"))
                else:
                    if not self.json_mode:
                        self._print(self.theme.dim("Zatrzymanie jest już w toku…"))
                continue

            if kind == "done":
                done = True
                continue
            if kind == "error":
                failure = item
                continue

            event = item
            self.observe_event(event)
            if self.json_mode:
                self._print(json.dumps(event, ensure_ascii=False, default=str), flush=True)
                if event.get("type") == "result":
                    result = event.get("data")
                continue

            if event.get("type") == "delta":
                saw_delta = True
                streamed_text += str(event.get("data", ""))
                if not answer_open:
                    self._print(f"\n{self.theme.bold('Platon')}  ", end="", flush=True)
                    answer_open = True
                self._print(str(event.get("data", "")), end="", flush=True)
            elif event.get("type") == "progress":
                if answer_open:
                    self._print()
                    answer_open = False
                data = event.get("data") or {}
                status = data.get("status", "done")
                symbol = "✓" if status not in {"error", "partial"} else "!"
                self._print(self.theme.dim(f"  {symbol} {data.get('tool', 'tool')} [{status}]"))
            elif event.get("type") == "result":
                result = event.get("data")

        worker.join(timeout=1)
        self.active_stop = None
        if answer_open:
            self._print()
        if failure is not None:
            raise failure
        if result is None:
            raise RuntimeError("Agent run ended without a result event.")
        if not self.json_mode:
            answer = str(result.get("answer") or "")
            self._render_result(result, saw_delta=saw_delta and streamed_text.endswith(answer))
        return result

    def _render_result(self, payload: dict[str, Any], *, saw_delta: bool) -> None:
        answer = payload.get("answer") or ""
        if answer and not saw_delta:
            self._print(f"\n{self.theme.bold('Platon')}  {answer}")
        errors = payload.get("errors") or []
        if errors:
            self._print(self.theme.yellow("\nNieukończone elementy:"))
            for error in errors:
                if isinstance(error, dict):
                    category = error.get("category", "error")
                    message = error.get("message") or json.dumps(error, ensure_ascii=False, default=str)
                    retry = " · można ponowić" if error.get("retryable") else ""
                    self._print(f"  - [{category}] {message}{retry}")
                else:
                    self._print(f"  - {error}")
        status = payload.get("status", "unknown")
        color = self.theme.green if status == "completed" else self.theme.yellow
        elapsed = payload.get("elapsed_seconds")
        elapsed_text = f" · {elapsed:.2f}s" if isinstance(elapsed, (int, float)) else ""
        self._print(color(f"\n{status}{elapsed_text}"))
        if payload.get("can_retry"):
            self._print(self.theme.dim("Run można wznowić komendą /retry albo porzucić przez /discard."))
        if payload.get("interrupts"):
            self._print(self.theme.yellow("Oczekuję na odpowiedź lub zgodę. /resume wraca do pytań."))

    def execute(self, operation: Callable[[Event], Iterator[dict[str, Any]]]) -> dict[str, Any] | None:
        try:
            return self.run_stream(operation)
        except KeyboardInterrupt:
            self._error("Przerwano obsługę terminala.")
        except Exception as exc:
            LOGGER.error("Terminal chat request failed (exception=%s)", type(exc).__name__)
            text = str(exc)
            if "Errno 8" in text or "nodename nor servname provided" in text:
                self._error("Błąd DNS. Sprawdź Internet, VPN/proxy i adres usługi.")
            else:
                self._error(f"Błąd: {exc}")
        return None

    def review_pending(self) -> dict[str, Any] | None:
        payload: dict[str, Any] | None = None
        while pending := self.agent.pending_interrupts():
            decisions: dict[str, Any] = {}
            try:
                for review in pending:
                    value = review.get("value") or {}
                    if value.get("kind") == "clarification":
                        question = value.get("question", "Podaj brakującą informację:")
                        answer = ""
                        while not answer:
                            answer = self.input_fn(f"\n{self.theme.yellow('?')} {question} ").strip()
                        decisions[review["id"]] = {"answer": answer}
                        continue

                    choices = []
                    for action in value.get("action_requests", []):
                        description = action.get("description") or action.get("name", "action")
                        self._print(f"\n{self.theme.yellow('Wymagana zgoda:')} {description}")
                        self._print(json.dumps(action.get("args", {}), ensure_ascii=False, indent=2, default=str))
                        while True:
                            choice = self.input_fn("Zatwierdzić? [t/n]: ").strip().lower()
                            if choice in {"t", "tak", "y", "yes", "n", "nie", "no"}:
                                break
                        choices.append({"type": "approve" if choice in {"t", "tak", "y", "yes"} else "reject"})
                    decisions[review["id"]] = {"decisions": choices}
            except (KeyboardInterrupt, EOFError):
                self._print("\nDecyzja pozostaje oczekująca. Użyj /discard, aby porzucić run.")
                return payload

            payload = self.execute(
                lambda stop, decisions=decisions: self.agent.resume_stream(decisions, stop_event=stop)
            )
            if payload is None:
                return None
        return payload

    def _replace_agent(self, thread_id: str | None) -> None:
        if self.message_queue:
            raise ValueError("Najpierw wykonaj /queue run lub /queue clear, aby nie przenieść zadań do innej rozmowy.")
        new_agent = self.agent_factory(thread_id)
        old_agent = self.agent
        self.agent = new_agent
        old_agent.close()

    def _resolve_thread(self, selector: str) -> str:
        threads = self.agent.list_threads()
        if selector.isdigit():
            index = int(selector) - 1
            if 0 <= index < len(threads):
                return threads[index]["thread_id"]
        matches = [item["thread_id"] for item in threads if item["thread_id"].startswith(selector)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"Nie znaleziono wątku: {selector}")
        raise ValueError("Prefiks pasuje do wielu wątków; podaj więcej znaków.")

    def _show_threads(self) -> None:
        rows = self.agent.list_threads()
        if not rows:
            self._print("Brak zapisanych rozmów.")
            return
        for index, item in enumerate(rows, 1):
            marker = "*" if item["thread_id"] == self.agent.thread_id else " "
            short_id = item["thread_id"][:8]
            title = item.get("title") or "Nowa rozmowa"
            count = item.get("message_count", 0)
            self._print(f"{marker} {index:>2}. {short_id}  {title}  {self.theme.dim(f'({count})')}")

    def _show_history(self) -> None:
        history = self.agent.load_thread_history()
        if not history:
            self._print("Historia jest pusta.")
            return
        for message in history:
            role = {"user": "Ty", "assistant": "Platon", "system": "System"}.get(message.get("role"), "System")
            self._print(f"\n{self.theme.bold(role)}\n{message.get('content', '')}")

    def _show_help(self) -> None:
        self._print(
            """
/help              pokaż komendy
/new               rozpocznij nową rozmowę
/threads           pokaż zapisane rozmowy
/switch <nr|id>    przełącz rozmowę
/history           pokaż historię bieżącej rozmowy
/status            pokaż stan runu i konfigurację
/skills [nr]       lista plików skilli / podgląd SKILL.md
/memory [nr]       lista skonfigurowanych plików pamięci / podgląd
/steps             narzędzia i statusy ostatniego wykonania
/resume            odpowiedz na oczekujące pytania i zgody
/retry             wznów niedokończony run z checkpointu
/discard           porzuć oczekujący lub niedokończony run
/stop              porzuć oczekujący run (w trakcie pracy: Ctrl+C)
/queue add <tekst>  dodaj wiadomość do kolejki bieżącej rozmowy
/queue             pokaż kolejkę wiadomości
/queue run         wykonaj kolejkę w kolejności FIFO / wznów ją
/queue remove <nr> usuń wybraną wiadomość z kolejki
/queue clear       wyczyść kolejkę bez usuwania historii
/pet               pokaż kompana
/pets [nazwa]      wybierz kompana: labrador, kot, lis, off
/clear             wyczyść ekran
/exit              zakończ

Zakończ linię znakiem \\ i naciśnij Enter, aby pisać dalej.
Podczas pracy agenta Ctrl+C bezpiecznie zatrzymuje aktywny run.
Kolejka zatrzymuje się po błędzie, Stop lub nieudzielonej odpowiedzi.
Dodaj zadania przez /queue add przed uruchomieniem /queue run.
""".strip()
        )

    def context_files(self, kind: str) -> list[tuple[str, Path]]:
        """Resolve only configured virtual paths inside this agent's backend."""
        config = self.agent.agent_config
        root = Path(config.backend_root).resolve()
        files: dict[str, Path] = {}
        for virtual in getattr(config, kind, []):
            path = (root / virtual.replace("\\", "/").lstrip("/")).resolve()
            if not path.is_relative_to(root):
                continue
            candidates = sorted(path.glob("*/SKILL.md")) if kind == "skills" else [path]
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved.is_relative_to(root) and resolved.is_file():
                    files["/" + candidate.relative_to(root).as_posix()] = resolved
        return list(files.items())

    def _show_context(self, kind: str, selector: str) -> None:
        files = self.context_files(kind)
        if not files:
            self._print(f"Brak plików {kind} w konfiguracji tego agenta.")
            return
        if selector:
            if not selector.isdigit() or not 1 <= int(selector) <= len(files):
                raise ValueError(f"Użycie: /{kind} <numer z listy>")
            virtual, path = files[int(selector) - 1]
            with path.open(encoding="utf-8", errors="replace") as stream:
                content = stream.read(65_537)
            # File content is data; never emit embedded terminal control sequences.
            content = "".join(c for c in content if c in "\n\t" or c.isprintable())
            self._print(f"{virtual}\n{content[:65_536]}")
            if len(content) > 65_536:
                self._print("… podgląd ograniczony do 64 KiB znaków.")
            return
        self._print(f"{kind.upper()} · pliki w backendzie {self.agent.agent_config.backend_root}")
        for index, (virtual, _) in enumerate(files, 1):
            self._print(f"  {index}. {virtual}")
        self._print(f"/{kind} <nr> otwiera plik. Lista plików nie potwierdza ich użycia przez model.")

    def _handle_queue(self, argument: str) -> None:
        action, _, text = argument.partition(" ")
        text = text.strip()
        if not action:
            if not self.message_queue:
                self._print("Kolejka jest pusta. /queue add <tekst> dodaje zadanie.")
            for index, message in enumerate(self.message_queue, 1):
                self._print(f"  {index}. {message}")
        elif action == "add" and text:
            self.message_queue.append(text)
            self._print(f"Dodano do kolejki · oczekuje: {len(self.message_queue)}")
        elif action == "clear":
            self.message_queue.clear()
            self._print("Wyczyszczono kolejkę.")
        elif action == "remove" and text.isdigit() and 1 <= int(text) <= len(self.message_queue):
            self.message_queue.pop(int(text) - 1)
            self._print("Usunięto wiadomość z kolejki.")
        elif action == "run":
            self._drain_queue()
        else:
            self._error("Użycie: /queue [add <tekst> | run | remove <nr> | clear]")

    def _drain_queue(self) -> None:
        if not self.message_queue:
            self._print("Kolejka jest pusta.")
        while self.message_queue:
            if self.agent.pending_interrupts() or self.agent.can_retry():
                self._print(self.theme.yellow("Kolejka wstrzymana. Użyj /resume, /retry lub /discard, potem /queue run."))
                return
            message = self.message_queue.pop(0)
            self._print(f"\n{self.theme.bold('Ty')}  {message}")
            payload = self.execute(lambda stop, text=message: self.agent.stream(text, stop_event=stop))
            if payload is not None and payload.get("interrupts"):
                payload = self.review_pending()
            if payload is None or payload.get("status") != "completed":
                self._print(self.theme.yellow("Kolejka wstrzymana. Sprawdź /history i /status; /queue run wznawia pozostałe zadania."))
                return

    def handle_command(self, raw: str) -> bool:
        try:
            return self._handle_command(raw)
        except Exception as exc:
            self._error(f"Nie udało się wykonać komendy: {exc}")
            return True

    def _handle_command(self, raw: str) -> bool:
        command, _, argument = raw.partition(" ")
        command = command.lower()
        argument = argument.strip()
        if command in EXIT_COMMANDS:
            return False
        if command in {"/help", "/h", "/?"}:
            self._show_help()
        elif command == "/new":
            self._replace_agent(str(uuid4()))
            self._print(f"Nowa rozmowa: {self.theme.cyan(self.agent.thread_id)}")
        elif command in {"/threads", "/sessions"}:
            self._show_threads()
        elif command == "/switch":
            if not argument:
                self._error("Użycie: /switch <numer lub prefiks id>")
            else:
                try:
                    thread_id = self._resolve_thread(argument)
                    if thread_id != self.agent.thread_id:
                        self._replace_agent(thread_id)
                    self._print(f"Aktywny wątek: {self.theme.cyan(thread_id)}")
                    self._show_history()
                except ValueError as exc:
                    self._error(str(exc))
        elif command == "/history":
            self._show_history()
        elif command in {"/skills", "/memory"}:
            self._show_context(command[1:], argument)
        elif command == "/steps":
            self._print("\n".join(self.steps) or "Brak zdarzeń narzędzi w ostatnim wykonaniu.")
            self._print("To raport działań; backend nie udostępnia osobnego strumienia rozumowania.")
        elif command == "/status":
            pending = len(self.agent.pending_interrupts())
            retry = self.agent.can_retry()
            self._print(f"thread: {self.agent.thread_id}")
            self._print(f"model:  {self.agent.agent_config.model_name}")
            self._print(f"pending decisions: {pending} · retry: {'yes' if retry else 'no'}")
            self._print(f"kolejka: {len(self.message_queue)}")
        elif command == "/queue":
            self._handle_queue(argument)
        elif command == "/pet":
            art = LABRADOR if self.pet == "labrador" else "\n".join(PETS.get(self.pet, ("Kompan wyłączony.",)))
            self._print(self.theme.yellow(art))
        elif command == "/pets":
            if not argument:
                self._print("PETS · labrador · kot · lis · off\nWybierz: /pets <nazwa>")
            elif argument in PETS or argument == "off":
                self.pet = argument
                self._print(f"Kompan: {argument} (wybór na tę sesję)")
            else:
                self._error("Nieznany kompan. Wpisz /pets.")
        elif command == "/resume":
            if self.agent.pending_interrupts():
                self.review_pending()
            else:
                self._print("Brak oczekujących pytań lub zgód. Niedokończone zadanie wznowisz przez /retry.")
        elif command == "/retry":
            if not self.agent.can_retry():
                self._error("Nie ma niedokończonego runu do wznowienia.")
            else:
                payload = self.execute(lambda stop: self.agent.retry_stream(stop_event=stop))
                if payload is not None:
                    self.review_pending()
        elif command in {"/discard", "/stop"}:
            if self.agent.discard_pending_run():
                self._print("Porzucono oczekujący run. Możesz wysłać nowe zadanie.")
            else:
                self._print("Nie ma runu do porzucenia.")
        elif command == "/clear":
            if getattr(self.out, "isatty", lambda: False)():
                self._print("\033[2J\033[H", end="", flush=True)
            else:
                self._print("\n" * 3)
            self.banner()
        else:
            self._error(f"Nieznana komenda: {command}. Użyj /help.")
        return True

    def interactive(self) -> int:
        self.banner()
        self._show_history()
        if self.agent.pending_interrupts():
            self._print(self.theme.yellow("Bieżąca rozmowa oczekuje na Twoją decyzję."))
            self.review_pending()
        elif self.agent.can_retry():
            self._print(self.theme.yellow("Bieżąca rozmowa ma niedokończony run. Użyj /retry lub /discard."))

        while True:
            try:
                user_input = self._read_message()
            except KeyboardInterrupt:
                self._print("\nWpisz /exit, aby zakończyć.")
                continue
            except EOFError:
                self._print("\nKoniec.")
                return 0

            if not user_input:
                continue
            if user_input.startswith("/") or user_input.lower() in EXIT_COMMANDS:
                if not self.handle_command(user_input):
                    self._print("Koniec.")
                    return 0
                continue
            if self.agent.pending_interrupts():
                self._error("Najpierw odpowiedz na oczekujące pytanie lub użyj /discard.")
                self.review_pending()
                continue
            if self.agent.can_retry():
                self._error("Najpierw użyj /retry albo /discard.")
                continue

            payload = self.execute(
                lambda stop, text=user_input: self.agent.stream(text, stop_event=stop)
            )
            if payload is not None:
                self.review_pending()

    def one_shot(self, prompt: str) -> int:
        if self.agent.pending_interrupts():
            self._error("Wątek oczekuje na interaktywną decyzję. Uruchom CLI bez --prompt.")
            return 2
        if self.agent.can_retry():
            self._error("Wątek ma niedokończony run. Uruchom CLI i użyj /retry albo /discard.")
            return 2
        payload = self.execute(lambda stop: self.agent.stream(prompt, stop_event=stop))
        if payload is None:
            return 1
        if payload.get("interrupts"):
            self._error("Run oczekuje na interaktywną decyzję. Uruchom CLI bez --prompt.")
            return 2
        return 0 if payload.get("status") == "completed" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Platon terminal agent")
    parser.add_argument("-p", "--prompt", help="wykonaj jedno zadanie i zakończ")
    parser.add_argument("--thread", help="otwórz wskazany zapisany wątek")
    parser.add_argument("--json", action="store_true", help="emituj zdarzenia JSONL (z --prompt)")
    parser.add_argument("--no-color", action="store_true", help="wyłącz kolory ANSI")
    parser.add_argument("--verbose", action="store_true", help="pokaż techniczne logi runtime")
    parser.add_argument("--plain", action="store_true", help="klasyczny terminal bez pełnego ekranu")
    return parser


def _configure_windows_streams() -> None:
    """Avoid CP1250 crashes on Unicode terminal output and redirected JSONL."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _configure_windows_streams()
    args = _parser().parse_args(argv)
    if args.json and not args.prompt:
        _parser().error("--json wymaga --prompt")
    if not args.verbose and "PLATON_LOG_LEVEL" not in os.environ:
        LOGGER.setLevel(logging.WARNING)
    modern = None
    if not args.prompt and not args.plain and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from platon.cli_display import ModernTerminal, build_with_splash
            modern = ModernTerminal
        except ImportError:
            print("Pełny ekran wymaga pakietu rich. Uruchamiam klasyczny CLI.", file=sys.stderr)
    try:
        LOGGER.info("Starting terminal chat application")
        if modern is not None:
            agent = build_with_splash(lambda: _build_agent(args.thread), no_color=args.no_color)
        else:
            agent = _build_agent(args.thread)
    except Exception as exc:
        LOGGER.error("Terminal chat initialization failed (exception=%s)", type(exc).__name__)
        print(f"Init error: {exc}", file=sys.stderr)
        return 1

    client = modern(agent, no_color=args.no_color) if modern else TerminalClient(
        agent, color=False if args.no_color else None, json_mode=args.json,
    )
    try:
        return client.one_shot(args.prompt) if args.prompt else client.interactive()
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
