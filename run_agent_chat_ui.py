#!/usr/bin/env python3
from __future__ import annotations

import os

from aiohttp import web

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

load_dotenv()

from backend.agent_chat_ui import create_app


def main() -> int:
    host = os.getenv("AGENT_CHAT_UI_HOST", "127.0.0.1")
    port = int(os.getenv("AGENT_CHAT_UI_PORT", "8080"))
    web.run_app(create_app(), host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
