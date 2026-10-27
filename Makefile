.PHONY: build run cli api test

PYTHON_VERSION ?= 3.13

build:
	uv sync --locked --python $(PYTHON_VERSION)
	uv build

test:
	uv run --locked --python $(PYTHON_VERSION) python -m unittest discover -s tests -t .

run:
	uv run --locked --python $(PYTHON_VERSION) python run_agent_chat_ui.py

cli:
	uv run --locked --python $(PYTHON_VERSION) platon

api:
	uv run --locked --python $(PYTHON_VERSION) python run_backend.py
