from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import uuid4

from aiohttp import web

from platon.app_logging import LOGGER, configure_logging, log_call
STATE = web.AppKey("agent_runtime", dict)

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
configure_logging()

from platon.agent.agent_orchestrator import AgentOrchestrator
from platon.agent.tools.errors import error_details
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig


@log_call
def _build_agent(thread_id: str | None = None) -> AgentOrchestrator:
    defaults = AgentConfig()
    orchestrator_config = AgentOrchestratorConfig(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"),
        working_dir=os.getenv("AGENT_WORKING_DIR", str(defaults.backend_root)),
        sqlite_path=os.getenv(
            "AGENT_SQLITE_PATH",
            str(defaults.backend_root / "agent_threads.sqlite3"),
        ),
    )
    agent_config = AgentConfig(
        model_name=os.getenv("OLLAMA_MODEL", defaults.model_name),
        num_ctx=int(os.getenv("OLLAMA_NUM_CTX", str(defaults.num_ctx))),
        system_prompt=os.getenv("AGENT_SYSTEM_PROMPT", defaults.system_prompt),
        max_history_messages=int(
            os.getenv(
                "AGENT_MAX_HISTORY_MESSAGES",
                str(defaults.max_history_messages),
            )
        ),
        backend_root=os.getenv("AGENT_BACKEND_ROOT", str(defaults.backend_root)),
    )
    return AgentOrchestrator(
        config=orchestrator_config,
        agent_config=agent_config,
        thread_id=thread_id,
    )


def _build_ui_html() -> str:
    return """<!doctype html>
<html lang="pl">
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
    .sidebar-close, .sidebar-backdrop { display: none; }
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
    .history-title {
      padding: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .06em;
      text-transform: uppercase;
    }
    .history-list {
      min-height: 0;
      display: flex;
      flex: 1;
      flex-direction: column;
      gap: 4px;
      overflow-y: auto;
    }
    .history-item {
      width: 100%;
      padding: 10px;
      overflow: hidden;
      border: 0;
      border-radius: 8px;
      background: transparent;
      cursor: pointer;
      font-size: 13px;
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .history-item:hover { background: #f0f0ed; }
    .history-item.active {
      background: #e7e7e3;
      font-weight: 600;
    }
    .history-empty {
      padding: 8px;
      color: var(--muted);
      font-size: 12px;
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
      min-width: 0;
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

    .queue-panel { margin-top: 8px; padding: 10px; border: 1px solid var(--border); border-radius: 10px; font-size: 13px; }
    .queue-panel ol { margin: 8px 0 0; padding-left: 20px; }
    .queue-panel li { overflow-wrap: anywhere; margin-top: 4px; }
    .queue-panel button, .stop { cursor: pointer; padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--soft); }
    .stop:disabled { opacity: .4; cursor: default; }

    @media (max-width: 760px) {
      .shell, .shell.collapsed { grid-template-columns: minmax(0, 1fr); }
      .sidebar {
        position: fixed;
        inset: 0 auto 0 0;
        z-index: 8;
        width: min(84vw, 320px);
        min-width: 0;
        padding-top: calc(14px + env(safe-area-inset-top));
        padding-bottom: calc(14px + env(safe-area-inset-bottom));
        box-shadow: var(--shadow);
        transform: translateX(-105%);
        transition: transform 180ms ease;
      }
      .shell.mobile-sidebar-open .sidebar { transform: translateX(0); }
      .sidebar-backdrop {
        position: fixed;
        inset: 0;
        z-index: 7;
        display: block;
        background: rgba(0, 0, 0, .38);
      }
      .sidebar-backdrop[hidden] { display: none; }
      .brand { justify-content: space-between; }
      .brand-name { margin-right: auto; }
      .sidebar-close { display: grid; }
      .history-item, .new-chat { min-height: 44px; }
      .main { grid-template-rows: 58px minmax(0, 1fr) auto; }
      .topbar { padding: 8px 12px; }
      .topbar h1 { font-size: 14px; }
      .shortcut { display: none; }
      .chat { padding: 20px 14px; gap: 22px; }
      .welcome { padding: 0 12px 10vh; }
      .welcome h2 { font-size: 32px; }
      .message { font-size: 15px; }
      .message.user { max-width: 90%; }
      .message.system { width: 100%; margin: 0; }
      .message.system form { display: grid; gap: 10px; margin-top: 10px; }
      .message.system form textarea, .message.system form select,
      .message.system form button, .message.system > button { width: 100%; min-height: 44px; font-size: 16px; }
      .message.system pre { max-width: 100%; overflow-x: auto; }
      .composer {
        position: relative;
        padding: 10px 12px calc(8px + env(safe-area-inset-bottom));
        border-top: 1px solid var(--border);
        background: #fff;
      }
      .composer form { gap: 6px; padding: 6px 7px 6px 14px; border-radius: 20px; }
      .composer textarea { font-size: 16px; }
      .send { width: 40px; height: 40px; flex-basis: 40px; }
      .stop { min-height: 40px; white-space: nowrap; }
      .stop:disabled { display: none; }
      .queue-panel { max-height: min(28vh, 220px); overflow-y: auto; }
      .meta { margin-top: 6px; }
    }
  </style>
</head>
<body>
  <div id="shell" class="shell">
    <aside id="sidebar" class="sidebar">
      <div class="brand"><span class="brand-mark">P</span><span class="brand-name">Platon</span><button id="sidebar-close" class="icon-button sidebar-close" type="button" aria-label="Zamknij menu">×</button></div>
      <button id="new-chat" class="new-chat" type="button"><span>＋</span>New chat</button>
      <div class="history-title">History</div>
      <div id="history-list" class="history-list">
        <div class="history-empty">No conversations yet.</div>
      </div>
      <div class="sidebar-note">Local test interface<br>Supervisor + specialists</div>
    </aside>
    <div id="sidebar-backdrop" class="sidebar-backdrop" hidden></div>

    <main class="main">
      <header class="topbar">
        <div class="topbar-left">
          <button id="sidebar-toggle" class="icon-button" type="button" aria-label="Otwórz menu" aria-controls="sidebar" aria-expanded="false">☰</button>
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
          <button id="stop" class="stop" type="button" disabled>Zatrzymaj</button>
        </form>
        <div id="queue-panel" class="queue-panel" hidden>
          <span id="queue-count"></span>
          <button id="resume-queue" type="button" hidden>Wznów kolejkę</button>
          <button id="clear-queue" type="button">Wyczyść kolejkę</button>
          <ol id="queue-list"></ol>
        </div>
        <div id="meta" class="meta">AI can make mistakes. Check important information.</div>
      </section>
    </main>
  </div>

  <script>
    const shell = document.getElementById("shell");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const sidebarBackdrop = document.getElementById("sidebar-backdrop");
    const mobileView = window.matchMedia("(max-width: 760px)");
    const chat = document.getElementById("chat");
    const form = document.getElementById("chat-form");
    const prompt = document.getElementById("prompt");
    const send = document.getElementById("send");
    const meta = document.getElementById("meta");
    const historyList = document.getElementById("history-list");
    const stopButton = document.getElementById("stop");
    const queuePanel = document.getElementById("queue-panel");
    const queueList = document.getElementById("queue-list");
    const resumeQueueButton = document.getElementById("resume-queue");
    let activeThreadId = null;
    let pendingReviews = [];
    let unfinishedRun = false;
    let busy = false;
    let ready = false;
    let stopRequested = false;
    let remoteRunning = false;
    let queuePaused = false;
    const messageQueue = [];

    function closeSidebar() {
      const wasOpen = shell.classList.contains("mobile-sidebar-open");
      shell.classList.remove("mobile-sidebar-open");
      sidebarBackdrop.hidden = true;
      sidebarToggle.setAttribute("aria-expanded", "false");
      sidebarToggle.setAttribute("aria-label", "Otwórz menu");
      if (wasOpen && mobileView.matches) sidebarToggle.focus();
    }

    function focusPrompt() {
      if (!mobileView.matches) prompt.focus();
    }

    function updateControls() {
      prompt.disabled = !ready;
      send.disabled = !ready;
      prompt.placeholder = busy || unfinishedRun || pendingReviews.length
        ? "Dodaj wiadomość do kolejki..." : "Napisz do Platona...";
      stopButton.disabled = stopRequested || !(busy || remoteRunning || unfinishedRun || pendingReviews.length);
      document.getElementById("new-chat").disabled = busy || messageQueue.length > 0;
      queuePanel.hidden = messageQueue.length === 0;
      document.getElementById("queue-count").textContent =
        `${queuePaused ? "Kolejka wstrzymana" : "W kolejce"}: ${messageQueue.length}`;
      resumeQueueButton.hidden = !queuePaused;
      queueList.replaceChildren();
      messageQueue.forEach((text, index) => {
        const item = document.createElement("li");
        item.textContent = text;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Usuń";
        remove.onclick = () => { messageQueue.splice(index, 1); updateControls(); };
        item.appendChild(remove);
        queueList.appendChild(item);
      });
    }

    async function runOperation(url, data, text = null) {
      if (busy) return;
      busy = true;
      stopRequested = false;
      updateControls();
      if (text !== null) addMessage("user", "Ty", text);
      showThinking();
      meta.textContent = "Platon pracuje...";
      try {
        const payload = await runStream(url, data);
        activeThreadId = payload.thread_id;
        renderMessages(payload.messages);
        showOutcome(payload);
        renderReviews(payload.interrupts);
        meta.textContent = payload.status === "stopped" ? "Zatrzymano zadanie."
          : payload.status === "completed" ? "Odpowiedź gotowa." : "Zadanie wymaga Twojej uwagi.";
        await loadConversationList();
      } catch (error) {
        document.getElementById("thinking")?.remove();
        addMessage("system", "Błąd", error.message);
        queuePaused = true;
        meta.textContent = "Kolejka wstrzymana. Sprawdź stan rozmowy przed ponowieniem zadania.";
        try { await loadConversationList(); } catch (_) { /* Preserve the original error. */ }
      } finally {
        busy = false;
        stopRequested = false;
        updateControls();
        focusPrompt();
        drainQueue();
      }
    }

    function drainQueue() {
      if (!ready || busy || queuePaused || unfinishedRun || pendingReviews.length || !messageQueue.length) return;
      const text = messageQueue.shift();
      runOperation("/api/chat", { message: text, thread_id: activeThreadId }, text);
    }

    function renderReviews(interrupts = []) {
      document.getElementById("reviews")?.remove();
      pendingReviews = interrupts;
      updateControls();
      if (!interrupts.length) return;
      meta.textContent = "Waiting for your input.";
      const panel = addMessage("system", "Input required", "");
      panel.id = "reviews";
      const reviewForm = document.createElement("form");
      const selections = [];
      for (const review of interrupts) {
        const choices = [];
        if (review.value.kind === "clarification") {
          const label = document.createElement("label");
          label.textContent = review.value.question;
          const answer = document.createElement("textarea");
          answer.required = true;
          label.appendChild(answer);
          reviewForm.appendChild(label);
          selections.push({ id: review.id, answer });
          continue;
        }
        for (const action of review.value.action_requests) {
          const details = document.createElement("pre");
          details.style.whiteSpace = "pre-wrap";
          details.style.overflowWrap = "anywhere";
          details.textContent = `${action.description || action.name}\\n${JSON.stringify(action.args, null, 2)}`;
          const label = document.createElement("label");
          label.textContent = `${action.name}: `;
          const select = document.createElement("select");
          select.required = true;
          for (const [value, text] of [["", "Choose a decision"], ["approve", "Approve"], ["reject", "Reject"]]) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = text;
            select.appendChild(option);
          }
          label.appendChild(select);
          reviewForm.append(details, label);
          choices.push(select);
        }
        selections.push({ id: review.id, choices });
      }
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.textContent = "Continue";
      reviewForm.appendChild(submit);
      reviewForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy) return;
        submit.disabled = true;
        const decisions = Object.fromEntries(selections.map(({ id, choices, answer }) => [
          id, answer ? { answer: answer.value } : { decisions: choices.map((select) => ({ type: select.value })) },
        ]));
        try {
          await runOperation("/api/resume", { thread_id: activeThreadId, decisions });
        } finally {
          submit.disabled = false;
        }
      });
      panel.lastElementChild.appendChild(reviewForm);
      chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" });
    }

    function showWelcome() {
      chat.replaceChildren();
      const welcome = document.createElement("div");
      welcome.id = "welcome";
      welcome.className = "welcome";
      const title = document.createElement("h2");
      title.textContent = "How can I help?";
      const subtitle = document.createElement("p");
      subtitle.textContent = "Ask about your collections or search the web.";
      welcome.append(title, subtitle);
      chat.appendChild(welcome);
    }

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

    function renderMessages(messages) {
      if (!messages.length) {
        showWelcome();
        return;
      }
      chat.replaceChildren();
      messages.forEach((message) => {
        if (message.role === "user") addMessage("user", "Ty", message.content);
        if (message.role === "assistant") addMessage("agent", "Platon", message.content);
        if (message.role === "system") addMessage("system", "System", message.content);
      });
    }

    function renderConversations(conversations) {
      historyList.replaceChildren();
      if (!conversations.length) {
        const empty = document.createElement("div");
        empty.className = "history-empty";
        empty.textContent = "No conversations yet.";
        historyList.appendChild(empty);
        return;
      }

      conversations.forEach((conversation) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "history-item";
        item.classList.toggle("active", conversation.thread_id === activeThreadId);
        item.textContent = conversation.title;
        item.title = conversation.title;
        item.addEventListener("click", () => openConversation(conversation.thread_id));
        historyList.appendChild(item);
      });
    }

    async function readJson(response) {
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Unknown error");
      return payload;
    }

    async function runStream(url, data) {
      const response = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!response.ok) await readJson(response);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let result = null;
      let output = null;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split("\\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "delta") {
            document.getElementById("thinking")?.remove();
            output ||= addMessage("agent", "Platon", "");
            output.lastElementChild.textContent += event.data;
          } else if (event.type === "progress") {
            meta.textContent = "Platon wykonuje zadanie...";
          } else if (event.type === "queued") {
            meta.textContent = `Wiadomość czeka na wykonanie (miejsce ${event.data.position}).`;
          } else if (event.type === "result") {
            result = event.data;
          } else if (event.type === "error") {
            throw new Error(event.data.message);
          }
        }
        if (done) break;
      }
      if (!result) throw new Error("Connection ended before the result was received. Reload history before retrying.");
      return result;
    }

    function showOutcome(payload) {
      unfinishedRun = Boolean(payload.can_retry);
      updateControls();
      if (payload.status === "partial" || payload.status === "error") {
        const details = payload.errors.map(error => typeof error === "string" ? error : error.message).join("\\n");
        const message = addMessage("system", "Incomplete work", details);
        if (payload.can_retry) {
          message.id = "unfinished";
          const button = document.createElement("button");
          button.textContent = "Continue unfinished run";
          button.onclick = async () => {
            if (busy) return;
            button.disabled = true;
            try {
              await runOperation("/api/retry", { thread_id: activeThreadId });
            } finally {
              button.disabled = false;
            }
          };
          message.appendChild(button);
        }
      }
    }

    async function loadConversationList() {
      const payload = await readJson(await fetch("/api/conversations"));
      activeThreadId = payload.active_thread_id;
      unfinishedRun = Boolean(payload.can_retry);
      remoteRunning = Boolean(payload.running);
      updateControls();
      renderConversations(payload.conversations);
      if (payload.can_retry && !document.getElementById("unfinished")) {
        showOutcome({ status: "partial", errors: [{message: "An unfinished run can be continued from its checkpoint."}], can_retry: true });
        chat.lastElementChild.id = "unfinished";
      }
      return payload;
    }

    async function openConversation(threadId) {
      if (busy || messageQueue.length) return;
      if (threadId === activeThreadId) { closeSidebar(); return; }
      try {
        const payload = await readJson(
          await fetch(`/api/conversations/${encodeURIComponent(threadId)}`),
        );
        activeThreadId = payload.thread_id;
        unfinishedRun = Boolean(payload.can_retry);
        renderMessages(payload.messages);
        renderReviews(payload.interrupts);
        await loadConversationList();
        closeSidebar();
        focusPrompt();
      } catch (error) {
        addMessage("system", "Error", error.message || "Could not load this chat.");
      }
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

    sidebarToggle.addEventListener("click", () => {
      if (!mobileView.matches) {
        shell.classList.toggle("collapsed");
        return;
      }
      const isOpen = shell.classList.toggle("mobile-sidebar-open");
      sidebarBackdrop.hidden = !isOpen;
      sidebarToggle.setAttribute("aria-expanded", String(isOpen));
      sidebarToggle.setAttribute("aria-label", isOpen ? "Zamknij menu" : "Otwórz menu");
      if (isOpen) document.getElementById("sidebar-close").focus();
    });
    document.getElementById("sidebar-close").addEventListener("click", closeSidebar);
    sidebarBackdrop.addEventListener("click", closeSidebar);
    mobileView.addEventListener("change", closeSidebar);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeSidebar();
    });

    document.getElementById("new-chat").addEventListener("click", async () => {
      if (busy || messageQueue.length) return;
      try {
        const payload = await readJson(
          await fetch("/api/reset", { method: "POST" }),
        );
        activeThreadId = payload.thread_id;
        unfinishedRun = false;
        closeSidebar();
        showWelcome();
        renderReviews();
        meta.textContent = "New conversation ready.";
        await loadConversationList();
        focusPrompt();
      } catch (error) {
        addMessage(
          "system",
          "Error",
          error.message || "Could not start a new chat.",
        );
      }
    });

    prompt.addEventListener("input", resizePrompt);
    prompt.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !mobileView.matches) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = prompt.value.trim();
      if (!text || !ready) return;
      if (queuePaused && !busy && !messageQueue.length) queuePaused = false;
      messageQueue.push(text);
      prompt.value = "";
      resizePrompt();
      updateControls();
      drainQueue();
    });

    stopButton.addEventListener("click", async () => {
      queuePaused = true;
      stopRequested = true;
      updateControls();
      meta.textContent = "Zatrzymuję zadanie. Kolejka jest wstrzymana.";
      try {
        const payload = await readJson(await fetch("/api/stop", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: activeThreadId }),
        }));
        if (!payload.running) {
          unfinishedRun = Boolean(payload.can_retry);
          renderMessages(payload.messages);
          renderReviews(payload.interrupts);
          await loadConversationList();
          meta.textContent = "Zatrzymano zadanie. Kolejka jest wstrzymana.";
        }
      } catch (error) {
        addMessage("system", "Błąd", error.message);
      } finally {
        stopRequested = false;
        updateControls();
      }
    });

    resumeQueueButton.addEventListener("click", () => {
      queuePaused = false;
      updateControls();
      drainQueue();
    });
    document.getElementById("clear-queue").addEventListener("click", () => {
      messageQueue.length = 0;
      queuePaused = false;
      updateControls();
    });

    focusPrompt();

    Promise.all([
      loadConversationList(),
      fetch("/api/history").then(readJson),
    ])
      .then(([list, messages]) => {
        renderMessages(messages);
        renderReviews(list.interrupts);
        if (list.can_retry) showOutcome({ status: "partial", errors: [{message: "An unfinished run can be continued from its checkpoint."}], can_retry: true });
        ready = true;
        updateControls();
      })
      .catch((error) => {
        showWelcome();
        addMessage("system", "Error", error.message || "Could not load chat history.");
      });
    updateControls();
  </script>
</body>
</html>
"""


async def index(_: web.Request) -> web.Response:
    return web.Response(text=_build_ui_html(), content_type="text/html")


def _activate_thread(app: web.Application, thread_id: str) -> list[dict[str, str]]:
    """Switch the UI to an existing conversation without merging histories."""
    old_agent: AgentOrchestrator = app[STATE]["agent"]
    if old_agent.thread_id == thread_id:
        return app[STATE]["history"]
    if not old_agent.thread_exists(thread_id):
        raise LookupError("Conversation not found.")

    new_agent = _build_agent(thread_id=thread_id)
    new_history = new_agent.load_thread_history()
    app[STATE]["agent"] = new_agent
    app[STATE]["history"] = new_history
    app[STATE]["interrupts"] = new_agent.pending_interrupts()
    app[STATE]["can_retry"] = new_agent.can_retry()
    old_agent.close()
    return new_history


def _lock(app):
    return app[STATE]["run_lock"]


def _executor(app):
    return app[STATE]["executor"]


async def _stream_response(request, operation, thread_id=None):
    lock = _lock(request.app)
    state = request.app[STATE]
    thread_id = thread_id or state["agent"].thread_id
    if lock.locked() and thread_id != state["agent"].thread_id:
        return web.json_response({"error": "Poczekaj na zakończenie pracy przed zmianą rozmowy."}, status=409)
    run = {"id": str(uuid4()), "thread_id": thread_id, "stop_event": Event()}
    state["queued_runs"].append(run)
    response = None
    try:
        if lock.locked():
            response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-cache"})
            await response.prepare(request)
            await response.write((json.dumps({"type": "queued", "data": {"thread_id": thread_id,
                                 "position": len(state["queued_runs"])}}, ensure_ascii=False) + "\n").encode("utf-8"))
        async with lock:
            state["queued_runs"].remove(run)
            state["active_run"] = run
            try:
                return await _execute_stream(request, operation, run, response)
            finally:
                state["active_run"] = None
    finally:
        if run in state["queued_runs"]:
            state["queued_runs"].remove(run)


async def _execute_stream(request, operation, run, response=None):
    """Keep the run lock until execution and persistence finish, including disconnects."""
    thread_id = run["thread_id"]
    try:
        LOGGER.info("Accepted chat operation (thread_switch=%s)", bool(thread_id))
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def deliver(event):
            # Publish completion even when the browser has stopped reading the response.
            if event and event["type"] == "result":
                payload = event["data"]
                request.app[STATE]["history"] = payload["messages"]
                request.app[STATE]["conversation_cache"] = payload.pop("conversations")
                request.app[STATE]["interrupts"] = payload["interrupts"]
                request.app[STATE]["can_retry"] = payload["can_retry"]
            queue.put_nowait(event)

        def execute():
            try:
                if thread_id:
                    _activate_thread(request.app, thread_id)
                agent = request.app[STATE]["agent"]
                LOGGER.info("Executing chat operation (agent=%s)", type(agent).__name__)
                for event in operation(agent, run["stop_event"]):
                    if event["type"] == "result":
                        event["data"].pop("result", None)
                        event["data"]["messages"] = agent.load_thread_history()
                        event["data"]["conversations"] = agent.list_threads()
                    loop.call_soon_threadsafe(deliver, event)
            except Exception as exc:
                LOGGER.exception("Chat operation failed")
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "data": error_details(exc)})
            finally:
                LOGGER.info("Chat operation worker finished")
                loop.call_soon_threadsafe(queue.put_nowait, None)

        future = loop.run_in_executor(_executor(request.app), execute)
        disconnected = False
        try:
            while (event := await queue.get()) is not None:
                if response is None:
                    if event["type"] == "error":
                        category = event["data"]["category"]
                        status = 404 if category == "lookup" else 409 if category == "validation" else 500
                        return web.json_response({"error": event["data"]["message"]}, status=status)
                    response = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-cache"})
                    await response.prepare(request)
                if not disconnected:
                    try:
                        await response.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                    except ConnectionResetError:
                        disconnected = True
            if response is not None and not disconnected:
                await response.write_eof()
            return response or web.json_response({"error": "No execution result."}, status=500)
        finally:
            # A disconnected browser must not release the run lock while tools are still executing.
            await asyncio.shield(future)
    finally:
        LOGGER.info("Chat operation stream closed")


async def _request_data(request):
    try:
        data = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text=json.dumps({"error": "Request body must be valid JSON."}), content_type="application/json")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text=json.dumps({"error": "Request body must be an object."}), content_type="application/json")
    return data


async def chat(request):
    data = await _request_data(request)
    if not isinstance(data.get("message"), str) or not data["message"].strip():
        return web.json_response({"error": "Message must be nonempty text."}, status=400)
    thread_id = data.get("thread_id")
    if thread_id is not None and (not isinstance(thread_id, str) or not thread_id.strip()):
        return web.json_response({"error": "Invalid conversation id."}, status=400)
    return await _stream_response(request, lambda agent, stop: agent.stream(data["message"], stop_event=stop), thread_id)


async def resume_chat(request):
    data = await _request_data(request)
    if not isinstance(data.get("thread_id"), str) or not data["thread_id"].strip():
        return web.json_response({"error": "A conversation id is required."}, status=400)
    return await _stream_response(request, lambda agent, stop: agent.resume_stream(data.get("decisions"), stop_event=stop), data["thread_id"])


async def retry_chat(request):
    data = await _request_data(request)
    if not isinstance(data.get("thread_id"), str) or not data["thread_id"].strip():
        return web.json_response({"error": "A conversation id is required."}, status=400)
    return await _stream_response(request, lambda agent, stop: agent.retry_stream(stop_event=stop), data["thread_id"])


async def stop_chat(request):
    data = await _request_data(request)
    thread_id = data.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return web.json_response({"error": "Wymagany jest identyfikator rozmowy."}, status=400)
    state = request.app[STATE]
    active = state["active_run"]
    if active:
        if thread_id != active["thread_id"]:
            return web.json_response({"error": "Ta rozmowa nie ma aktywnego zadania."}, status=409)
        # Do not use the occupied worker or run lock to request cancellation.
        active["stop_event"].set()
        return web.json_response({"stopped": True, "running": True})
    if _lock(request.app).locked() or state["queued_runs"]:
        return web.json_response({"error": "Trwa zmiana stanu rozmowy. Spróbuj ponownie."}, status=409)
    async with _lock(request.app):
        agent = state["agent"]
        if thread_id != agent.thread_id:
            return web.json_response({"error": "Ta rozmowa nie jest aktywna."}, status=409)
        def discard():
            stopped = agent.discard_pending_run()
            return stopped, agent.load_thread_history(), agent.pending_interrupts(), agent.can_retry()
        stopped, messages, interrupts, can_retry = await asyncio.get_running_loop().run_in_executor(_executor(request.app), discard)
        state.update(history=messages, interrupts=interrupts, can_retry=can_retry)
        return web.json_response({"stopped": stopped, "running": False, "thread_id": thread_id,
                                  "messages": messages, "interrupts": interrupts, "can_retry": can_retry})


async def reset_chat(request):
    lock = _lock(request.app)
    if lock.locked() or request.app[STATE]["queued_runs"]:
        return web.json_response({"error": "Wait for the current run to finish."}, status=409)
    async with lock:
        def reset():
            old_agent = request.app[STATE]["agent"]
            request.app[STATE]["agent"] = _build_agent(thread_id=str(uuid4()))
            request.app[STATE]["history"] = []
            old_agent.close()
            LOGGER.info("Started a new conversation after reset")
        await asyncio.get_running_loop().run_in_executor(_executor(request.app), reset)
        request.app[STATE]["interrupts"] = []
        request.app[STATE]["can_retry"] = False
        return web.json_response({"status": "ok", "thread_id": request.app[STATE]["agent"].thread_id})


async def history(request):
    return web.json_response(request.app[STATE]["history"])


async def conversations(request):
    lock = _lock(request.app)
    if not lock.locked():
        async with lock:
            def read():
                agent = request.app[STATE]["agent"]
                return agent.list_threads(), agent.pending_interrupts(), agent.can_retry()
            rows, interrupts, can_retry = await asyncio.get_running_loop().run_in_executor(_executor(request.app), read)
            request.app[STATE]["conversation_cache"] = rows
            request.app[STATE]["interrupts"] = interrupts
            request.app[STATE]["can_retry"] = can_retry
    return web.json_response({"active_thread_id": request.app[STATE]["agent"].thread_id,
                              "conversations": request.app[STATE].get("conversation_cache", []),
                              "interrupts": request.app[STATE].get("interrupts", []),
                              "can_retry": request.app[STATE].get("can_retry", False),
                              "running": bool(request.app[STATE]["active_run"]),
                              "queue_length": len(request.app[STATE]["queued_runs"])})


async def conversation(request):
    lock = _lock(request.app)
    if lock.locked() or request.app[STATE]["queued_runs"]:
        return web.json_response({"error": "Wait for the current run to finish."}, status=409)
    async with lock:
        thread_id = request.match_info["thread_id"].strip()
        try:
            messages = await asyncio.get_running_loop().run_in_executor(_executor(request.app), _activate_thread, request.app, thread_id)
            def read():
                agent = request.app[STATE]["agent"]
                return agent.pending_interrupts(), agent.can_retry()
            interrupts, can_retry = await asyncio.get_running_loop().run_in_executor(_executor(request.app), read)
        except LookupError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        request.app[STATE]["interrupts"] = interrupts
        request.app[STATE]["can_retry"] = can_retry
        return web.json_response({"thread_id": thread_id, "messages": messages, "interrupts": interrupts, "can_retry": can_retry})


def create_app() -> web.Application:
    app = web.Application()
    app[STATE] = {}
    app[STATE]["agent"] = _build_agent()
    app[STATE]["history"] = app[STATE]["agent"].load_thread_history()
    app[STATE]["run_lock"] = asyncio.Lock()
    app[STATE]["active_run"] = None
    app[STATE]["queued_runs"] = []
    app[STATE]["executor"] = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")
    app[STATE]["conversation_cache"] = app[STATE]["agent"].list_threads()
    app.router.add_get("/", index)
    app.router.add_get("/api/history", history)
    app.router.add_get("/api/conversations", conversations)
    app.router.add_get("/api/conversations/{thread_id}", conversation)
    app.router.add_post("/api/chat", chat)
    app.router.add_post("/api/resume", resume_chat)
    app.router.add_post("/api/retry", retry_chat)
    app.router.add_post("/api/stop", stop_chat)
    app.router.add_post("/api/reset", reset_chat)
    app.on_cleanup.append(_close_agent)
    LOGGER.info("Chat web application initialized")
    return app


async def _close_agent(app):
    if active := app[STATE]["active_run"]:
        active["stop_event"].set()
    async with _lock(app):
        LOGGER.info("Shutting down chat application resources")
        await asyncio.get_running_loop().run_in_executor(_executor(app), app[STATE]["agent"].close)
        app[STATE]["executor"].shutdown(wait=True)
        LOGGER.info("Chat application shutdown complete")
