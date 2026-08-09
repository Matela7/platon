from __future__ import annotations

import os
from typing import Any

from aiohttp import web

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

load_dotenv()

from agent.agent_orchestrator import AgentOrchestrator
from agent.models.agent_config import AgentConfig
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig


def _extract_last_assistant_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            if message.get("role") != "assistant":
                continue
            content = message.get("content")
        elif getattr(message, "type", None) != "ai":
            continue

        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [
                item if isinstance(item, str) else item.get("text", "")
                for item in content
                if isinstance(item, (str, dict))
            ]
            if text := "\n".join(part.strip() for part in parts if part.strip()):
                return text

    return "The model returned a response that could not be displayed."


def _build_agent() -> AgentOrchestrator:
    defaults = AgentConfig()
    orchestrator_config = AgentOrchestratorConfig(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"),
        sqlite_path=os.getenv("AGENT_SQLITE_PATH"),
    )
    agent_config = AgentConfig(
        model_name=os.getenv("OLLAMA_MODEL", defaults.model_name),
        system_prompt=os.getenv("AGENT_SYSTEM_PROMPT", defaults.system_prompt),
        max_history_messages=int(
            os.getenv(
                "AGENT_MAX_HISTORY_MESSAGES",
                str(defaults.max_history_messages),
            )
        ),
    )
    return AgentOrchestrator(
        config=orchestrator_config,
        agent_config=agent_config,
    )


def _build_ui_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Platon Agent</title>
  <style>
    :root {
      --bg: #fff;
      --sidebar: #f7f7f5;
      --text: #202123;
      --muted: #71716f;
      --border: #e6e6e3;
      --soft: #f1f1ef;
      --accent: #181818;
      --error: #fff5df;
      --shadow: 0 8px 30px rgba(0, 0, 0, .08);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      overflow: hidden;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    }
    button, textarea { font: inherit; }
    button { color: inherit; }

    .shell {
      width: 100%;
      height: 100vh;
      height: 100dvh;
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      transition: grid-template-columns 180ms ease;
    }
    .shell.collapsed { grid-template-columns: 0 minmax(0, 1fr); }

    .sidebar {
      min-width: 260px;
      padding: 14px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      gap: 14px;
      background: var(--sidebar);
      border-right: 1px solid var(--border);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px;
      font-weight: 650;
    }
    .brand-mark {
      width: 30px;
      height: 30px;
      display: grid;
      place-items: center;
      border-radius: 9px;
      background: var(--accent);
      color: #fff;
      font-size: 13px;
    }
    .new-chat {
      width: 100%;
      padding: 11px 12px;
      display: flex;
      align-items: center;
      gap: 10px;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #fff;
      cursor: pointer;
      text-align: left;
    }
    .new-chat:hover, .icon-button:hover { background: #ececea; }
    .sidebar-note {
      margin-top: auto;
      padding: 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }

    .main {
      min-width: 0;
      min-height: 0;
      display: grid;
      grid-template-rows: 58px minmax(0, 1fr);
      position: relative;
    }
    .topbar {
      z-index: 2;
      padding: 9px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, .9);
      backdrop-filter: blur(12px);
    }
    .topbar-left { display: flex; align-items: center; gap: 10px; }
    .topbar h1 { margin: 0; font-size: 15px; font-weight: 650; }
    .status { color: var(--muted); font-size: 11px; }
    .status::before {
      content: "";
      width: 7px;
      height: 7px;
      margin-right: 6px;
      display: inline-block;
      border-radius: 50%;
      background: #22a06b;
    }
    .shortcut { color: var(--muted); font-size: 12px; }
    .icon-button {
      width: 36px;
      height: 36px;
      display: grid;
      place-items: center;
      border: 0;
      border-radius: 8px;
      background: transparent;
      cursor: pointer;
      font-size: 19px;
    }

    .chat {
      min-height: 0;
      padding: 36px max(22px, calc((100% - 820px) / 2)) 150px;
      display: flex;
      flex-direction: column;
      gap: 28px;
      overflow-x: hidden;
      overflow-y: auto;
      overscroll-behavior: contain;
      scroll-behavior: smooth;
    }
    .welcome { margin: auto; padding-bottom: 18vh; text-align: center; }
    .welcome h2 {
      margin: 0 0 10px;
      font: 500 clamp(30px, 4vw, 44px)/1.1 Georgia, serif;
      letter-spacing: -.035em;
    }
    .welcome p { margin: 0; color: var(--muted); }
    .message {
      width: min(100%, 820px);
      line-height: 1.65;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      animation: appear 180ms ease-out;
    }
    .message small {
      margin-bottom: 7px;
      display: block;
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }
    .message.user {
      width: fit-content;
      max-width: min(78%, 680px);
      margin-left: auto;
      padding: 11px 16px;
      border-radius: 18px;
      background: var(--soft);
    }
    .message.user small { display: none; }
    .message.system {
      width: fit-content;
      margin: 0 auto;
      padding: 10px 14px;
      border-radius: 10px;
      background: var(--error);
      color: #6b4f12;
      font-size: 14px;
    }

    .composer {
      position: absolute;
      right: 0;
      bottom: 0;
      left: 0;
      z-index: 3;
      padding: 22px max(22px, calc((100% - 820px) / 2)) 18px;
      background: linear-gradient(transparent, #fff 28%);
    }
    .composer form {
      width: min(100%, 820px);
      margin: auto;
      padding: 8px 8px 8px 18px;
      display: flex;
      align-items: flex-end;
      border: 1px solid var(--border);
      border-radius: 24px;
      background: #fff;
      box-shadow: var(--shadow);
    }
    textarea {
      width: 100%;
      min-height: 40px;
      max-height: 160px;
      padding: 10px 8px 8px 0;
      resize: none;
      overflow-y: auto;
      border: 0;
      outline: 0;
      background: transparent;
      color: var(--text);
      line-height: 1.4;
    }
    .send {
      width: 38px;
      height: 38px;
      flex: 0 0 38px;
      padding: 0;
      display: grid;
      place-items: center;
      border: 0;
      border-radius: 50%;
      background: var(--accent);
      color: #fff;
      cursor: pointer;
      font-size: 18px;
    }
    .send:disabled { cursor: wait; opacity: .35; }
    .meta {
      width: min(100%, 820px);
      margin: 8px auto 0;
      color: var(--muted);
      font-size: 11px;
      text-align: center;
    }
    .thinking { display: inline-flex; gap: 4px; padding: 10px 0; }
    .thinking i {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #888;
      animation: pulse 1s infinite ease-in-out;
    }
    .thinking i:nth-child(2) { animation-delay: 120ms; }
    .thinking i:nth-child(3) { animation-delay: 240ms; }
    @keyframes appear {
      from { opacity: 0; transform: translateY(7px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes pulse {
      0%, 70%, 100% { opacity: .3; transform: translateY(0); }
      35% { opacity: 1; transform: translateY(-3px); }
    }

    @media (max-width: 760px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { display: none; }
      .chat { padding: 24px 16px 140px; }
      .composer { padding-inline: 12px; }
      .message.user { max-width: 90%; }
      .shortcut { display: none; }
    }
  </style>
</head>
<body>
  <div id="shell" class="shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">P</span><span>Platon</span></div>
      <button id="new-chat" class="new-chat" type="button"><span>＋</span>New chat</button>
      <div class="sidebar-note">Local test interface<br>Supervisor + specialists</div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="topbar-left">
          <button id="sidebar-toggle" class="icon-button" type="button" aria-label="Toggle sidebar">☰</button>
          <div><h1>Platon Agent</h1><div class="status">Local</div></div>
        </div>
        <div class="shortcut">Enter to send · Shift+Enter for a new line</div>
      </header>

      <section id="chat" class="chat" aria-live="polite">
        <div id="welcome" class="welcome">
          <h2>How can I help?</h2>
          <p>Ask about your collections or search the web.</p>
        </div>
      </section>

      <section class="composer">
        <form id="chat-form">
          <textarea id="prompt" rows="1" placeholder="Message Platon..." aria-label="Message"></textarea>
          <button id="send" class="send" type="submit" aria-label="Send message">↑</button>
        </form>
        <div id="meta" class="meta">AI can make mistakes. Check important information.</div>
      </section>
    </main>
  </div>

  <script>
    const shell = document.getElementById("shell");
    const chat = document.getElementById("chat");
    const form = document.getElementById("chat-form");
    const prompt = document.getElementById("prompt");
    const send = document.getElementById("send");
    const meta = document.getElementById("meta");

    function addMessage(role, label, text) {
      document.getElementById("welcome")?.remove();
      const article = document.createElement("article");
      article.className = `message ${role}`;
      const author = document.createElement("small");
      author.textContent = label;
      const body = document.createElement("div");
      body.textContent = text;
      article.append(author, body);
      chat.appendChild(article);
      chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" });
      return article;
    }

    function showThinking() {
      const message = addMessage("agent", "Platon", "");
      message.id = "thinking";
      message.lastElementChild.innerHTML =
        '<span class="thinking"><i></i><i></i><i></i></span>';
    }

    function resizePrompt() {
      prompt.style.height = "40px";
      prompt.style.height = Math.min(prompt.scrollHeight, 160) + "px";
    }

    document.getElementById("sidebar-toggle").addEventListener("click", () => {
      shell.classList.toggle("collapsed");
    });

    document.getElementById("new-chat").addEventListener("click", async () => {
      try {
        await fetch("/api/reset", { method: "POST" });
        window.location.reload();
      } catch {
        addMessage("system", "Error", "Could not start a new chat.");
      }
    });

    prompt.addEventListener("input", resizePrompt);
    prompt.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = prompt.value.trim();
      if (!text || send.disabled) return;

      addMessage("user", "You", text);
      prompt.value = "";
      resizePrompt();
      send.disabled = true;
      showThinking();
      meta.textContent = "Platon is thinking...";

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Unknown error");

        document.getElementById("thinking")?.remove();
        addMessage("agent", "Platon", payload.answer);
        meta.textContent = payload.elapsed_seconds
          ? `Answered in ${payload.elapsed_seconds}s`
          : "Response ready.";
      } catch (error) {
        document.getElementById("thinking")?.remove();
        addMessage("system", "Error", error.message || "The response could not be loaded.");
        meta.textContent = "Something went wrong. You can try again.";
      } finally {
        send.disabled = false;
        prompt.focus();
      }
    });

    prompt.focus();
  </script>
</body>
</html>
"""


async def index(_: web.Request) -> web.Response:
    return web.Response(text=_build_ui_html(), content_type="text/html")


async def chat(request: web.Request) -> web.Response:
    agent: AgentOrchestrator = request.app["agent"]
    history: list[dict[str, str]] = request.app["history"]

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Request body must be valid JSON."}, status=400)

    user_input = str(data.get("message", "")).strip()
    if not user_input:
        return web.json_response({"error": "Message cannot be empty."}, status=400)

    try:
        payload = agent.invoke(user_input=user_input, history=history)
        assistant_text = payload.get("answer") or _extract_last_assistant_text(
            payload.get("result", {}).get("messages", [])
        )
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    history.extend(
        [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": assistant_text},
        ]
    )
    return web.json_response(
        {
            "answer": assistant_text,
            "elapsed_seconds": payload.get("elapsed_seconds"),
        }
    )


async def reset_chat(request: web.Request) -> web.Response:
    try:
        request.app["agent"] = _build_agent()
        request.app["history"] = []
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    app = web.Application()
    app["agent"] = _build_agent()
    app["history"] = []
    app.router.add_get("/", index)
    app.router.add_post("/api/chat", chat)
    app.router.add_post("/api/reset", reset_chat)
    return app
