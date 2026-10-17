.PHONY: build run

PYTHON_VERSION ?= 3.13

build:
	uv sync --python $(PYTHON_VERSION)

run:
	@powershell.exe -NoProfile -Command "try { Invoke-RestMethod 'http://localhost:11434/api/version' -TimeoutSec 2 | Out-Null } catch { Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden -ErrorAction Stop; Start-Sleep -Seconds 2 }"
	uv run --no-sync python run_agent_chat_ui.py
