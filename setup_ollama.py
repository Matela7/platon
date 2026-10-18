"""Cross-platform Ollama bootstrapper for the Platon project.

The module intentionally uses only the Python standard library. It can therefore
be executed before the project dependencies from ``pyproject.toml`` are installed,
or through ``uv run`` after the environment has been created.

Examples:
    python setup_ollama.py
    uv run python setup_ollama.py --dry-run
    python setup_ollama.py --models ornith-1.5:9b
    python setup_ollama.py --write-env
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_MODELS: Final[tuple[str, ...]] = ("ornith-1.5:35b", "ornith-1.5:9b")
DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:11434"
OLLAMA_INSTALL_SCRIPT: Final[str] = "https://ollama.com/install.sh"
OLLAMA_MACOS_ARCHIVE: Final[str] = "https://ollama.com/download/Ollama-darwin.zip"
OLLAMA_API_TIMEOUT_SECONDS: Final[float] = 5.0


class SetupError(RuntimeError):
    """Raised when Ollama cannot be installed, started, or verified."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Result of a command executed by the installer."""

    command: tuple[str, ...]
    return_code: int


CommandRunner = Callable[[Sequence[str]], CommandResult]


def _format_command(command: Sequence[str]) -> str:
    """Format a command for logs without changing how it is executed."""
    if platform.system() == "Windows":
        return subprocess.list2cmdline(list(command))
    return " ".join(shlex_quote(part) for part in command)


def shlex_quote(value: str) -> str:
    """Quote one shell-display argument without importing a POSIX-only helper."""
    if not value:
        return "''"
    return "'" + value.replace("'", "'\\''") + "'"


def run_command(command: Sequence[str]) -> CommandResult:
    """Run a process and convert operating-system failures to SetupError."""
    command_tuple = tuple(command)
    print(f"> {_format_command(command_tuple)}")
    try:
        completed = subprocess.run(command_tuple, check=False)
    except OSError as exc:
        raise SetupError(f"Unable to start command '{command_tuple[0]}': {exc}") from exc
    result = CommandResult(command_tuple, completed.returncode)
    if result.return_code != 0:
        raise SetupError(
            f"Command failed with exit code {result.return_code}: "
            f"{_format_command(result.command)}"
        )
    return result


def command_exists(command: str) -> bool:
    """Return whether an executable is available on PATH."""
    return shutil.which(command) is not None


def ollama_executable() -> str | None:
    """Find Ollama on PATH or in its conventional Windows installation path."""
    on_path = shutil.which("ollama")
    if on_path:
        return on_path
    if platform.system() == "Windows":
        candidates = (
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def install_linux() -> None:
    """Install Ollama on Linux using the official installer."""
    if not command_exists("curl"):
        raise SetupError("Linux installation requires curl to be installed first.")
    run_command(("sh", "-c", f"curl -fsSL {OLLAMA_INSTALL_SCRIPT} | sh"))


def install_macos() -> None:
    """Install Ollama on macOS using Homebrew or the official application archive."""
    if command_exists("brew"):
        run_command(("brew", "install", "--cask", "ollama"))
        return
    if not command_exists("curl"):
        raise SetupError("macOS installation requires curl or Homebrew.")

    with tempfile.TemporaryDirectory(prefix="ollama-install-") as directory:
        archive = Path(directory) / "Ollama-darwin.zip"
        print(f"Downloading Ollama from {OLLAMA_MACOS_ARCHIVE}")
        try:
            urllib.request.urlretrieve(OLLAMA_MACOS_ARCHIVE, archive)
        except (OSError, urllib.error.URLError) as exc:
            raise SetupError(f"Unable to download Ollama for macOS: {exc}") from exc
        try:
            with zipfile.ZipFile(archive) as extracted:
                extracted.extractall(directory)
        except (OSError, zipfile.BadZipFile) as exc:
            raise SetupError(f"Unable to unpack the Ollama macOS archive: {exc}") from exc
        application = Path(directory) / "Ollama.app"
        if not application.is_dir():
            raise SetupError("The Ollama macOS archive did not contain Ollama.app.")
        run_command(("cp", "-R", str(application), "/Applications/Ollama.app"))
        run_command(("open", "/Applications/Ollama.app"))


def install_windows() -> None:
    """Install Ollama on Windows using winget."""
    if not command_exists("winget"):
        raise SetupError(
            "Ollama is not installed and winget is unavailable. "
            "Install App Installer from Microsoft Store, then run this script again."
        )
    run_command(("winget", "install", "--id", "Ollama.Ollama", "--exact", "--accept-package-agreements", "--accept-source-agreements"))


def install_ollama() -> None:
    """Install Ollama for the current operating system."""
    if ollama_executable():
        print("Ollama is already installed.")
        return
    installers = {"Linux": install_linux, "Darwin": install_macos, "Windows": install_windows}
    installer = installers.get(platform.system())
    if installer is None:
        raise SetupError(f"Unsupported operating system: {platform.system()}")
    installer()
    if not ollama_executable():
        raise SetupError("Ollama installation completed, but the executable was not found.")


def start_ollama() -> None:
    """Start Ollama using the native service/application mechanism."""
    system = platform.system()
    if system == "Linux" and command_exists("systemctl"):
        run_command(("systemctl", "enable", "--now", "ollama"))
        return
    if system == "Darwin":
        run_command(("open", "-a", "Ollama"))
        return
    if system == "Windows":
        executable = ollama_executable()
        if executable is not None:
            subprocess.Popen(
                (executable, "serve"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def wait_for_server(base_url: str, *, timeout_seconds: float = 30.0) -> None:
    """Wait until the Ollama HTTP API is reachable or raise a clear error."""
    url = f"{base_url.rstrip('/')}/api/version"
    deadline = time.monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=OLLAMA_API_TIMEOUT_SECONDS) as response:
                if response.status == 200:
                    return
                last_error = SetupError(f"Ollama returned HTTP {response.status} for {url}.")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(0.5)
    raise SetupError(
        f"Ollama is not reachable at {base_url} after {timeout_seconds:.0f} seconds. "
        "Start Ollama and check the URL."
    ) from last_error


def pull_models(models: Sequence[str], executable: str) -> None:
    """Download all requested models, stopping on the first failed download."""
    for model in models:
        if not model.strip():
            raise SetupError("Model names must not be empty.")
        run_command((executable, "pull", model))


def update_env(path: Path, *, base_url: str, models: Sequence[str]) -> None:
    """Update only Ollama settings in an env file, preserving all other entries."""
    values = {"OLLAMA_BASE_URL": base_url, "OLLAMA_MODEL": models[0]}
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output: list[str] = []
    written: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in values and not line.lstrip().startswith("#"):
            output.append(f"{key}={values[key]}")
            written.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in values.items() if key not in written)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    print(f"Updated Ollama settings in {path}.")


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(description="Install Ollama and Platon models.")
    parser.add_argument(
        "--models", nargs="+", default=list(DEFAULT_MODELS), metavar="MODEL",
        help="Models to download (default: both Ornith 35B and 9B).",
    )
    parser.add_argument(
        "--base-url", default=os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        help=f"Ollama API URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument("--write-env", action="store_true", help="Update .env with Ollama settings.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Env file to update.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing the system.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the installer CLI and return a process exit code."""
    args = build_parser().parse_args(argv)
    if not args.models:
        print("ERROR: At least one model is required.", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"Platform: {platform.system()}")
        print(f"Models: {', '.join(args.models)}")
        print(f"Ollama URL: {args.base_url}")
        print("Dry run complete; no changes were made.")
        return 0
    try:
        install_ollama()
        start_ollama()
        executable = ollama_executable()
        if executable is None:
            raise SetupError("Ollama executable was not found after installation.")
        wait_for_server(args.base_url)
        pull_models(args.models, executable)
        if args.write_env:
            update_env(args.env_file, base_url=args.base_url, models=args.models)
        print(f"Setup complete. Installed models: {', '.join(args.models)}")
        return 0
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


