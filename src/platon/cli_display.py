"""Interactive CLI display; all agent operations still use TerminalClient."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import os
import queue
import select
import sys
from threading import Event, Thread
from time import monotonic

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from platon.run_agent_chat import LABRADOR, LOGO, PETS, TerminalClient


COMMANDS = {
    "/help": "wszystkie komendy i skróty", "/new": "nowa rozmowa",
    "/threads": "zapisane rozmowy", "/switch": "przełącz rozmowę: numer lub ID",
    "/history": "historia rozmowy", "/status": "stan i model",
    "/skills": "pliki skilli; /skills <nr> otwiera podgląd",
    "/memory": "pliki pamięci; /memory <nr> otwiera podgląd",
    "/steps": "zdarzenia narzędzi", "/resume": "wróć do pytań i zgód",
    "/retry": "wznów niedokończone zadanie", "/stop": "zatrzymaj i wstrzymaj kolejkę",
    "/discard": "porzuć niedokończone zadanie", "/queue": "pokaż kolejkę",
    "/queue add": "dodaj zadanie do kolejki", "/queue run": "wznów kolejkę",
    "/queue pause": "wstrzymaj kolejkę po bieżącym zadaniu",
    "/queue remove": "usuń wiadomość: numer", "/queue clear": "wyczyść kolejkę",
    "/pets": "wybierz kompana: labrador, kot, lis, off",
    "/pet": "pokaż kompana", "/clear": "wyczyść widok", "/exit": "zakończ CLI",
}

def suggestions(text: str) -> list[str]:
    if not text.startswith("/"):
        return []
    choices = list(COMMANDS) + [f"/pets {name}" for name in (*PETS, "off")]
    return [command for command in choices if command.startswith(text.lower())]


def safe_text(value: str) -> str:
    return "".join(char for char in value if char in "\n\t" or char.isprintable())


def splash(elapsed: float, width: int):
    frame = int(elapsed * 8)
    pulse = " " * (frame % 24) + "━━━"
    logo = LOGO if width >= 48 else "PLATON CLI"
    return Panel(Group(
        Text(logo, style="bold cyan"), Text("\nLOCAL INTELLIGENCE · YOUR WORKSPACE", style="dim"),
        Text("\n" + LABRADOR, style="yellow"),
        Text(f"\n  {pulse:<28}", style="bright_cyan"),
        Text(f"  Inicjalizacja agenta i lokalnych zasobów · {elapsed:.1f}s", style="bold"),
        Text("  Pierwsze uruchomienie może potrwać dłużej.", style="dim"),
    ), title="PLATON / START", border_style="cyan", padding=(1, 2))


def build_with_splash(factory, *, no_color=False):
    """Animate actual initialization, without artificial delays or fake percentages."""
    console = Console(no_color=no_color or "NO_COLOR" in os.environ)
    started = monotonic()
    # Initialize on the caller thread; animation never touches model/SQLite state.
    with Live(console=console, get_renderable=lambda: splash(monotonic() - started, console.width),
              refresh_per_second=8, transient=True):
        return factory()


class Keyboard:
    """Nonblocking native terminal input, with terminal state restored on exit."""

    def __init__(self):
        self.buffer = ""

    @contextmanager
    def open(self):
        if os.name == "nt":
            yield self
        else:
            import termios
            import tty
            previous = termios.tcgetattr(sys.stdin.fileno())
            try:
                tty.setcbreak(sys.stdin.fileno())
                yield self
            finally:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, previous)

    def read(self):
        if os.name == "nt":
            import msvcrt
            if not msvcrt.kbhit():
                return None
            char = msvcrt.getwch()
            if char in {"\x00", "\xe0"}:
                return {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT",
                        "G": "HOME", "O": "END", "I": "PAGEUP", "Q": "PAGEDOWN",
                        "S": "DELETE"}.get(msvcrt.getwch(), "")
        else:
            if not self.buffer:
                if not select.select([sys.stdin], [], [], 0)[0]:
                    return None
                self.buffer = os.read(sys.stdin.fileno(), 4096).decode("utf-8", errors="replace")
            sequences = {"\x1b[A": "UP", "\x1b[B": "DOWN", "\x1b[C": "RIGHT", "\x1b[D": "LEFT",
                         "\x1b[H": "HOME", "\x1b[F": "END", "\x1b[5~": "PAGEUP", "\x1b[6~": "PAGEDOWN",
                         "\x1b[3~": "DELETE"}
            for sequence, key in sequences.items():
                if self.buffer.startswith(sequence):
                    self.buffer = self.buffer[len(sequence):]
                    return key
            char, self.buffer = self.buffer[0], self.buffer[1:]
        return {"\r": "ENTER", "\n": "NEWLINE" if os.name == "nt" else "ENTER",
                "\x03": "STOP", "\x04": "EXIT", "\x1a": "EXIT", "\x08": "BACKSPACE",
                "\x7f": "BACKSPACE", "\t": "TAB", "\x1b": "ESC", "\x15": "CLEAR"}.get(char, char)


class ModernTerminal(TerminalClient):
    def __init__(self, agent, *, no_color=False, console=None, agent_factory=None):
        options = {} if agent_factory is None else {"agent_factory": agent_factory}
        super().__init__(agent, color=False, input_fn=self.ask, **options)
        self.console = console or Console(no_color=no_color or "NO_COLOR" in os.environ)
        self.events = queue.Queue()
        self.answers = queue.Queue()
        self.worker = None
        self.cancel_requested = Event()
        self.paused = False
        self.pending = False
        self.retryable = False
        self.closing = False
        self.discard_after_stop = False
        self.switching = False
        self.question = ""
        self.saved_draft = ""
        self.draft = ""
        self.cursor = 0
        self.history = []
        self.history_index = 0
        self.completion_index = 0
        self.scroll = 0
        self.transcript = ""
        self.timeline = deque(maxlen=80)
        self.started = monotonic()
        self.pet = "labrador"
        self.state = "Gotowy"

    @property
    def busy(self):
        return self.worker is not None

    def _print(self, text="", *, end="\n", flush=False):
        self.events.put(("text", safe_text(str(text)) + end))

    def _error(self, text):
        self._print(f"Błąd: {text}")

    def observe_event(self, event):
        super().observe_event(event)
        if event.get("type") == "progress":
            data = event.get("data") or {}
            self.events.put(("step", f"{monotonic() - self.started:5.1f}s  {data.get('tool', 'tool')} · {data.get('status', 'done')}"))
        elif event.get("type") == "delta":
            self.events.put(("state", "Piszę odpowiedź"))

    def ask(self, prompt):
        self.events.put(("question", safe_text(prompt)))
        answer = self.answers.get()
        if answer is None:
            raise KeyboardInterrupt
        return answer

    def execute(self, operation):
        def cancellable(stop):
            if self.cancel_requested.is_set():
                stop.set()
            yield from operation(stop)
        result = super().execute(cancellable)
        if result is None:
            self.last_result = {"status": "error"}
        return result

    def start_job(self, operation, *, switching=False):
        if self.busy:
            raise RuntimeError("CLI already has an active operation")
        self.cancel_requested.clear()
        self.started = monotonic()
        self.last_result = None
        self.state = "Pracuję"
        self.switching = switching
        def run():
            failed = False
            pending = retry = False
            try:
                operation()
            except Exception as exc:
                failed = True
                self._error(str(exc))
            finally:
                try:
                    pending = bool(self.agent.pending_interrupts())
                    retry = self.agent.can_retry()
                except Exception as exc:
                    failed = True
                    self._error(str(exc))
                self.events.put(("finished", (failed, pending, retry)))
        self.worker = Thread(target=run, name="platon-cli-operation", daemon=True)
        self.worker.start()

    def send_message(self, text):
        self._print(f"\nTy  {text}\n")
        payload = self.execute(lambda stop: self.agent.stream(text, stop_event=stop))
        if payload is not None and not self.cancel_requested.is_set():
            self.review_pending()

    def stop(self):
        self.paused = True
        self.cancel_requested.set()
        if self.busy:
            self.state = "Zatrzymywanie…"
            self.request_stop()
            # Wake a review prompt too; never leave a worker waiting on input.
            if self.question:
                self.answers.put(None)
                self.question = ""
                self.draft, self.saved_draft = self.saved_draft, ""
                self.cursor = len(self.draft)
            self.discard_after_stop = True
        else:
            self.start_job(lambda: self.handle_command("/discard"))

    def pump(self):
        for _ in range(1000):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "text":
                self.transcript = (self.transcript + value)[-150_000:]
            elif kind == "step":
                self.timeline.append(safe_text(value))
            elif kind == "state":
                if not self.cancel_requested.is_set():
                    self.state = value
            elif kind == "question":
                if self.cancel_requested.is_set():
                    self.answers.put(None)
                else:
                    self.saved_draft, self.draft = self.draft, ""
                    self.cursor = 0
                    self.question = value
                    self.state = "Czekam na Ciebie"
                    self._print(f"\n{value}\n")
            elif kind == "finished":
                self.worker.join()
                self.worker = None
                self.switching = False
                failed, self.pending, self.retryable = value
                status = (self.last_result or {}).get("status")
                if failed or self.pending or self.retryable or status in {"stopped", "error", "partial", "interrupted"}:
                    self.paused = True
                self.state = "Wymaga uwagi" if self.pending or self.retryable or failed else "Gotowy"
                if self.discard_after_stop:
                    self.discard_after_stop = False
                    if self.pending or self.retryable:
                        self.start_job(lambda: self.handle_command("/discard"))
        if not self.busy and not self.closing and not self.paused and not self.pending and not self.retryable and self.message_queue:
            message = self.message_queue.pop(0)
            self.start_job(lambda: self.send_message(message))

    def submit(self, text):
        text = text.strip()
        if not text:
            return
        if text in {"/exit", "/quit", "/q"}:
            self.closing = True
            if self.busy:
                self.stop()
            return
        if text == "/stop":
            self.stop()
            return
        if text.split()[0] == "/pets":
            self.handle_command(text)
            return
        if text == "/pet":
            self._print("\n".join(PETS.get(self.pet, ("Kompan wyłączony.",))))
            return
        if text == "/queue run":
            if self.busy and self.cancel_requested.is_set():
                self._error("Poczekaj na zakończenie zatrzymywania zadania.")
                return
            self.paused = False
            self._print("Kolejka wznowiona." if not self.pending and not self.retryable else "Najpierw /resume, /retry albo /discard.")
            return
        if text == "/queue pause":
            self.paused = True
            return
        if text == "/queue" or text.startswith("/queue "):
            if self.switching:
                self._error("Poczekaj na zakończenie przełączania rozmowy.")
                return
            self._handle_queue(text.partition(" ")[2])
            return
        if text in {"/help", "/h", "/?"}:
            self._print("\n".join(f"{command:<18} {description}" for command, description in COMMANDS.items()))
            self._print("\nTab: uzupełnij · ↑↓: podpowiedzi/historia · PgUp/PgDn: przewijaj\nCtrl+C: Stop · Ctrl+J: nowa linia (Windows) · \\ + Enter: nowa linia\nWiadomości podczas pracy trafiają do kolejki. Odpowiedź na pytanie wpisz w wyróżnionym polu.\nPamięć i skille: /memory <nr>, /skills <nr>. /pets zmienia kompana.\nAktywność pokazuje zdarzenia narzędzi, nie prywatne rozumowanie modelu.")
            return
        if text == "/clear":
            self.transcript = ""
            self.scroll = 0
            return
        if text.split()[0] in {"/skills", "/memory", "/steps"} and not self.switching:
            self.handle_command(text)
            return
        if text == "/status" and self.busy:
            self._print(f"{self.state} · model {self.agent.agent_config.model_name}\n"
                        f"thread {self.agent.thread_id} · kolejka {len(self.message_queue)}")
            return
        if self.question and not text.startswith("/"):
            self._print(f"Twoja odpowiedź: {text}")
            self.answers.put(text)
            self.question = ""
            self.draft, self.saved_draft = self.saved_draft, ""
            self.cursor = len(self.draft)
            self.state = "Pracuję"
            return
        if text.startswith("/"):
            if self.busy:
                self._error("Podczas pracy: /stop, /queue, /help, /pets. Pozostałe komendy po zakończeniu.")
            else:
                self.start_job(lambda: self.handle_command(text), switching=text.split()[0] in {"/new", "/switch"})
            return
        if self.switching:
            self._error("Poczekaj na zakończenie przełączania rozmowy.")
            return
        self.message_queue.append(text)
        if self.pending or self.retryable or self.paused:
            self._print("Wiadomość w kolejce. Rozwiąż oczekujące zadanie, potem /queue run.")

    def key(self, key):
        matches = suggestions(self.draft)
        if key == "STOP":
            self.stop()
        elif key == "EXIT":
            self.submit("/exit")
        elif key == "TAB" and matches:
            self.draft = matches[self.completion_index % len(matches)] + " "
            self.cursor = len(self.draft)
            self.completion_index = 0
        elif key in {"UP", "DOWN"}:
            offset = -1 if key == "UP" else 1
            if matches:
                self.completion_index = (self.completion_index + offset) % len(matches)
            elif self.history:
                self.history_index = max(0, min(len(self.history), self.history_index + offset))
                self.draft = self.history[self.history_index] if self.history_index < len(self.history) else ""
                self.cursor = len(self.draft)
        elif key in {"PAGEUP", "PAGEDOWN"}:
            self.scroll = max(0, self.scroll + (8 if key == "PAGEUP" else -8))
        elif key == "LEFT":
            self.cursor = max(0, self.cursor - 1)
        elif key == "RIGHT":
            self.cursor = min(len(self.draft), self.cursor + 1)
        elif key in {"HOME", "END"}:
            self.cursor = 0 if key == "HOME" else len(self.draft)
        elif key == "BACKSPACE" and self.cursor:
            self.draft = self.draft[:self.cursor - 1] + self.draft[self.cursor:]
            self.cursor -= 1
        elif key == "DELETE":
            self.draft = self.draft[:self.cursor] + self.draft[self.cursor + 1:]
        elif key in {"ESC", "CLEAR"}:
            self.draft, self.cursor = "", 0
        elif key == "NEWLINE" or (key == "ENTER" and self.draft.endswith("\\")):
            if key == "ENTER":
                self.draft = self.draft[:-1]
                self.cursor = len(self.draft)
            self.draft = self.draft[:self.cursor] + "\n" + self.draft[self.cursor:]
            self.cursor += 1
        elif key == "ENTER":
            text, self.draft = self.draft, ""
            self.cursor, self.completion_index = 0, 0
            if text.strip():
                self.history.append(text)
                self.history_index = len(self.history)
                self.scroll = 0
                self.submit(text)
        elif len(key) == 1 and key.isprintable():
            self.draft = self.draft[:self.cursor] + key + self.draft[self.cursor:]
            self.cursor += 1
            self.completion_index = 0

    def pet_panel(self):
        frame = int(monotonic() * 3) % 4
        face = "\n".join(PETS.get(self.pet, ()))
        if self.busy and not self.question:
            face += ("  /", "  |", "  \\", "  |")[frame]
        mood = "? Czekam na Ciebie" if self.question else ("Pracujemy " + (".  ", ".. ", "...", " ..")[frame] if self.busy else "Gotowy na spacer po kodzie")
        return Panel(Text(face + "\n" + mood, style="yellow"), title=self.pet.upper(), border_style="yellow")

    def render(self):
        width, height = self.console.size
        compact = width < 90 or height < 24
        frame = "◐◓◑◒"[int(monotonic() * 6) % 4] if self.busy else "●"
        header = Text(f" {frame} PLATON CLI  /  {self.state}  ·  kolejka {len(self.message_queue)}" + (" [pauza]" if self.paused else ""), style="bold cyan")
        header.append(f"\n {self.agent.agent_config.model_name}  ·  {self.agent.thread_id[:12]}", style="dim")
        root = Layout()
        composer_height = 7 if height >= 24 else 5
        root.split_column(Layout(Panel(header, border_style="cyan"), size=4), Layout(name="body"), Layout(name="input", size=composer_height))
        chat_width = width if compact else width - 33
        lines = Text(self.transcript or "Witaj w PLATON CLI.\n\nNapisz zadanie. Tab podpowiada komendy.\n/help · /skills · /memory · /pets", overflow="fold").wrap(self.console, max(8, chat_width - 4))
        available = max(1, height - 4 - composer_height - 2)
        self.scroll = min(self.scroll, max(0, len(lines) - available))
        end = max(0, len(lines) - self.scroll)
        body = Text("\n").join(lines[max(0, end - available):end])
        chat = Panel(body, title="ROZMOWA", subtitle="PgUp / PgDn · historia" if self.scroll else "", border_style="blue")
        if compact:
            root["body"].update(chat)
        else:
            root["body"].split_row(Layout(chat), Layout(name="side", size=33))
            activity = Panel(Text("\n".join(list(self.timeline)[-6:]) or "Narzędzia pojawią się tutaj\npo otrzymaniu zdarzeń.\n\n/steps: pełna lista", style="cyan"), title="AKTYWNOŚĆ", border_style="cyan")
            queued = "\n".join(f"{i}. {text[:55]}" for i, text in enumerate(self.message_queue[:4], 1)) or "Brak oczekujących wiadomości"
            panels = [Layout(activity), Layout(Panel(Text(queued), title="KOLEJKA · FIFO", border_style="magenta"), size=5)]
            if self.pet != "off" and height >= 28:
                panels.append(Layout(self.pet_panel(), size=7))
            root["side"].split_column(*panels)
        matches = suggestions(self.draft)
        hint = "Tab: komendy · Ctrl+C: Stop · PgUp/PgDn: przewijaj · /help"
        if matches:
            chosen = matches[self.completion_index % len(matches)]
            hint = "  ".join(matches[max(0, self.completion_index - 1):self.completion_index + 3])
            hint += "\n→ " + chosen + " · " + COMMANDS.get(chosen, "wybierz kompana")
        elif self.busy and not self.question:
            hint = "Enter: dodaj do kolejki · /stop lub Ctrl+C: zatrzymaj"
        prompt = Text("› ", style="bold green")
        # Keep the cursor and surrounding text visible even for a long paste.
        start = max(0, self.cursor - max(10, width - 12))
        prompt.append(self.draft[start:self.cursor])
        prompt.append(self.draft[self.cursor:self.cursor + 1] or " ", style="reverse")
        prompt.append(self.draft[self.cursor + 1:self.cursor + max(10, width - 12)])
        title = "ODPOWIEDŹ NA PYTANIE / ZGODĘ" if self.question else "WIADOMOŚĆ"
        root["input"].update(Panel(Group(prompt, Text(hint, style="dim")), title=title,
                                   border_style="yellow" if self.question else "green"))
        return root

    def interactive(self):
        self._print("PLATON CLI · /help · /pets · /skills · /memory\n")
        def restore():
            self._show_history()
            if self.agent.pending_interrupts():
                self.review_pending()
        self.start_job(restore)
        keyboard = Keyboard()
        with keyboard.open(), Live(console=self.console, screen=True, auto_refresh=False,
                                   redirect_stdout=False, redirect_stderr=False) as live:
            while not self.closing or self.busy:
                try:
                    self.pump()
                    for _ in range(64):
                        key = keyboard.read()
                        if key is None:
                            break
                        self.key(key)
                    live.update(self.render(), refresh=True)
                    Event().wait(0.04)
                except KeyboardInterrupt:
                    self.stop()
        self.console.print("PLATON CLI zakończony. Rozmowa pozostaje w historii.")
        if self.message_queue:
            self.console.print(f"Niewysłane wiadomości z kolejki tej sesji: {len(self.message_queue)}")
        return 0

    def close(self):
        # Never close SQLite underneath an in-flight worker, even after UI failure.
        if self.busy:
            self.cancel_requested.set()
            self.request_stop()
            self.answers.put(None)
            self.worker.join()
            self.worker = None
        super().close()
