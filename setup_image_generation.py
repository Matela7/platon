"""Standalone image setup entrypoint, also used by the packaged desktop."""
import sys
from pathlib import Path
_source = Path(__file__).resolve().parent / "src"
if _source.is_dir():
    sys.path.insert(0, str(_source))
from platon.backend.image_setup import *
if __name__ == "__main__":
    raise SystemExit(main())
