"""Explicit first-launch Ollama setup with pollable download progress."""
import json
import os
import secrets
import sys
import threading
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from platon.backend import ollama_setup

MODELS = ollama_setup.DEFAULT_MODELS
router = APIRouter(prefix="/setup", include_in_schema=False)
_lock = threading.Lock()
_state = {"status": "pending", "message": "Install Ollama and required models", "model": None, "completed": 0, "total": 0, "error": None}


def _update(**values):
    with _lock:
        _state.update(values)


def run_setup():
    try:
        base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        try:
            ollama_setup.wait_for_server(base, timeout_seconds=1)
        except ollama_setup.SetupError:
            _update(message="Installing and starting Ollama")
            ollama_setup.install_ollama()
            ollama_setup.start_ollama()
            ollama_setup.wait_for_server(base)
        with urllib.request.urlopen(base + "/api/tags", timeout=10) as response:
            installed = {item["name"] for item in json.load(response).get("models", [])}
        for model in MODELS:
            if model in installed:
                continue
            _update(model=model, message=f"Downloading {model}", completed=0, total=0)
            request = urllib.request.Request(base + "/api/pull", data=json.dumps({"model": model, "stream": True}).encode(), headers={"Content-Type": "application/json"})
            finished = False
            with urllib.request.urlopen(request, timeout=600) as response:
                for line in response:
                    progress = json.loads(line)
                    if progress.get("error"):
                        raise RuntimeError(progress["error"])
                    _update(message=progress.get("status", "Downloading"), completed=progress.get("completed", 0), total=progress.get("total", 0))
                    finished = progress.get("status") == "success"
            if not finished:
                raise RuntimeError(f"Download ended before success: {model}")
        with urllib.request.urlopen(base + "/api/tags", timeout=10) as response:
            verified = {item["name"] for item in json.load(response).get("models", [])}
        if not set(MODELS).issubset(verified):
            raise RuntimeError("Ollama did not confirm both installed models")
        if sys.platform == "win32":
            from platon.backend import image_setup
            directory = Path.cwd() / ".platon" / "agent" / "model-lora"
            directory.mkdir(parents=True, exist_ok=True)
            for item in image_setup.DOWNLOADS:
                _update(model=item.name, message=f"Preparing image generator: {item.name}", completed=0, total=0)
                archive = image_setup.download(item, directory, progress=lambda completed, total: _update(completed=completed, total=total))
                if archive.suffix == ".zip":
                    image_setup.install_archive(archive, directory)
        _update(status="completed", message="Models and application are ready", model=None, error=None)
    except Exception as exc:
        _update(status="error", message=str(exc), error=str(exc))


def _authorize(token):
    expected = os.getenv("PLATON_SETUP_TOKEN")
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Desktop setup token required")


@router.get("/status")
def status(x_platon_setup_token: str | None = Header(default=None)):
    _authorize(x_platon_setup_token)
    with _lock:
        return dict(_state)


@router.post("/start")
def start(x_platon_setup_token: str | None = Header(default=None)):
    _authorize(x_platon_setup_token)
    with _lock:
        if _state["status"] in {"running", "completed"}:
            return dict(_state)
        _state.update(status="running", message="Checking Ollama", error=None)
        result = dict(_state)
    threading.Thread(target=run_setup, name="platon-setup", daemon=True).start()
    return result
