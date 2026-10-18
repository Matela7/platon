.PHONY: build run cli test

PYTHON_VERSION ?= 3.13

build:
	uv sync --locked --python $(PYTHON_VERSION)
	uv build

test:
	uv run --locked --python $(PYTHON_VERSION) python -m unittest discover -s tests -t .

run:
	@powershell.exe -NoProfile -Command "try { Invoke-RestMethod 'http://localhost:11434/api/version' -TimeoutSec 2 | Out-Null } catch { Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden -ErrorAction Stop; Start-Sleep -Seconds 2 }"
	uv run --locked --python $(PYTHON_VERSION) python run_agent_chat_ui.py

cli:
	uv run --locked --python $(PYTHON_VERSION) platon
