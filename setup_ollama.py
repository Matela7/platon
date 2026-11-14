"""Standalone compatibility entrypoint for the packaged Ollama setup helper."""
import sys
from pathlib import Path

_source = Path(__file__).resolve().parent / "src"
if _source.is_dir():
    sys.path.insert(0, str(_source))
from platon.backend.ollama_setup import *

if __name__ == "__main__":
    raise SystemExit(main())
