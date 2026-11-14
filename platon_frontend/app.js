import {
  ApiError,
  chat,
  chatWithImages,
  deleteCurrentThread,
  deleteDocument,
  deleteImage,
  deleteSentImage,
  deleteThread,
  discard,
  getConfig,
  getSnapshot,
  imageUrl,
  sentImageUrl,
  initializeRuntime,
  listDocuments,
  listImages,
  listOllamaModels,
  listSentImages,
  listThreads,
  resume,
  retry,
  stop,
  updateConfig,
  uploadDocument,
} from "./api.js";
import { translateText } from "./i18n.js";

const DEFAULT_CONFIG = {
  orchestrator_config: {
    base_url: "http://localhost:11434",
    persist_dir: "./chroma_data",
    working_dir: "./",
    sqlite_path: null,
  },
  agent_config: {
    model_name: "gemma4:26b-a4b-it-qat",
    model_temperature: 0,
    system_prompt: "react_prompt.md",
    max_history_messages: 24,
    max_tool_output_chars: 20000,
    keep_alive: "30m",
    num_ctx: 16384,
    reasoning: false,
    debug: true,
    research_tool_limit: 6,
    coding_tool_limit: 15,
    database_tool_limit: 8,
    execution_timeout_seconds: 120,
    backend_root: "./.platon/agent",
    skills: ["/skills/"],
    memory: ["/memory/AGENTS.md"],
  },
};

const storage = {
  get: (key) => { try { return globalThis.localStorage?.getItem(key) ?? null; } catch { return null; } },
  set: (key, val) => {
    try { globalThis.localStorage?.setItem(key, val); } catch {}
    if (["platon.activeThreadId", "platon.theme", "platon.language", "platon.generatedImages", "platon.threadModels"].includes(key)) {
      globalThis.platonWindow?.setPreference?.(key, String(val))?.catch(() => {});
    }
  },
};

function getThreadModels() {
  try {
    const raw = storage.get("platon.threadModels");
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function setThreadModel(threadId, modelName) {
  if (!threadId) return;
  const models = getThreadModels();
  if (modelName) {
    models[threadId] = modelName;
  } else {
    delete models[threadId];
  }
  storage.set("platon.threadModels", JSON.stringify(models));
}

function getDefaultModel() {
  return state.defaultModel || state.config?.agent_config?.model_name || DEFAULT_CONFIG.agent_config.model_name;
}

const $ = (selector, root = globalThis.document) => (root ? root.querySelector(selector) : null);
const state = {
  config: null,
  snapshot: null,
  threads: [],
  documents: [],
  images: [],
  imageGalleryLoading: false,
  imageGalleryPending: false,
  imageGalleryRequest: 0,
  imageGalleryError: "",
  attachments: new Set(),
  pendingImages: [],
  selectedForAttachment: new Set(),
  busy: false,
  loadingAnimationIndex: 0,
  switching: false,
  backendBusy: false,
  stopRequested: false,
  collapsed: false,
  toastTimer: 0,
  threadSearchQuery: "",
  documentSearchQuery: "",
  documentCollection: "",
  modelRequest: 0,
  imageSearchQuery: "",
  lastSentMessage: "",
  generatedImages: {},
  theme: storage.get("platon.theme") || "system",
};

const elements = {
  sidebar: $(".sidebar"),
  threadList: $("#thread-list"),
  threadSearch: $("#thread-search"),
  conversation: $("#conversation"),
  conversationScroll: $("#conversation-scroll"),
  title: $("#conversation-title"),
  modelPill: $("#model-pill"),
  composerForm: $("#composer-form"),
  input: $("#message-input"),
  send: $("#send-button"),
  attach: $("#attach-document"),
  attachImage: $("#attach-image"),
  imagePicker: $("#image-picker"),
  imageAttachmentStrip: $("#image-attachment-strip"),
  documentPicker: $("#document-picker"),
  attachmentStrip: $("#attachment-strip"),
  stop: $("#stop-run"),
  retry: $("#retry-run"),
  discard: $("#discard-run"),
  status: $("#composer-status"),
  connection: $("#connection-status"),
  connectionLabel: $("#connection-label"),
  reconnectButton: $("#reconnect-button"),
  settingsDialog: $("#settings-dialog"),
  settingsForm: $("#settings-form"),
  settingsFields: $("#settings-fields"),
  documentsDialog: $("#documents-dialog"),
  tabDocRag: $("#tab-documents-rag"),
  tabDocSentImages: $("#tab-documents-sent-images"),
  docRagPanel: $("#documents-rag-panel"),
  docSentImagesPanel: $("#documents-sent-images-panel"),
  sentImagesGrid: $("#sent-images-grid"),
  sentImagesSearch: $("#sent-images-search"),
  refreshSentImages: $("#refresh-sent-images"),
  sentImagesStatus: $("#sent-images-status"),
  documentList: $("#document-list"),
  documentSearch: $("#document-search"),
  imageDialog: $("#images-dialog"),
  imageGrid: $("#image-grid"),
  imageSearch: $("#image-search"),
  scrollBottomBtn: $("#scroll-bottom-btn"),
  exportChatButton: $("#export-chat-button"),
  themeToggleButton: $("#theme-toggle-button"),
};

const fieldLabels = {
  base_url: "Adres Ollama",
  persist_dir: "Katalog kolekcji Chroma",
  working_dir: "Katalog roboczy",
  sqlite_path: "Ścieżka bazy SQLite (opcjonalnie)",
  model_name: "Model Ollama",
  model_temperature: "Temperatura",
  system_prompt: "Plik promptu systemowego",
  max_history_messages: "Liczba wiadomości w kontekście",
  max_tool_output_chars: "Limit znaków wyniku narzędzia",
  keep_alive: "Czas utrzymania modelu",
  num_ctx: "Okno kontekstu modelu",
  reasoning: "Włącz rozumowanie modelu",
  debug: "Tryb debugowania",
  research_tool_limit: "Limit narzędzi research",
  coding_tool_limit: "Limit narzędzi coding",
  database_tool_limit: "Limit narzędzi database",
  execution_timeout_seconds: "Limit czasu wykonania (s)",
  backend_root: "Katalog danych agenta",
  skills: "Ścieżki skills (jedna w wierszu)",
  memory: "Pliki pamięci (jeden w wierszu)",
};

const RAG_INSTRUCTIONS = "Use these indexed documents as sources for this request. Delegate document analysis to delegate_database and retrieve evidence through RAG from the specified collections before answering. Verify that retrieved passages belong to the selected filenames and source paths. If evidence is unavailable, explain what is missing.\nRAG sources (metadata only):\n";

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function formatInline(text) {
  // Protect code and links before applying emphasis, which otherwise changes
  // literal asterisks/underscores in code and in URL attributes.
  const tokens = [];
  const token = (html) => `\u0000${tokens.push(html) - 1}\u0000`;
  let result = escapeHtml(text).replace(/\u0000/g, "");
  result = result.replace(/`([^`\n]+)`/g, (_, code) => token(`<code class="inline-code">${code}</code>`));
  result = result.replace(/!?\[([^\]]*)\]\(([^\s)]+)\)/g, (match, title, escapedUrl) => {
    const filename = generatedImageFilenames(escapedUrl)[0];
    if (match.startsWith("!") && filename) {
      return token(`<img class="generated-image-inline" src="${escapeHtml(imageUrl(filename))}" alt="${title || "Wygenerowany obraz"}" loading="lazy">`);
    }
    if (!/^(https?:\/\/|#)/.test(escapedUrl) || match.startsWith("!")) return match;
    return token(`<a href="${escapedUrl}" target="_blank" rel="noopener noreferrer">${title}</a>`);
  });
  result = result.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  result = result.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  result = result.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  result = result.replace(/(^|[^\*])\*([^\*\n]+)\*([^\*]|$)/g, "$1<em>$2</em>$3");
  result = result.replace(/(^|[^_])_([^_\n]+)_([^_]|$)/g, "$1<em>$2</em>$3");
  result = result.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  return result.replace(/\u0000(\d+)\u0000/g, (_, index) => tokens[Number(index)]);
}

export function generatedImageFilenames(value) {
  const text = typeof value === "string" ? value : "";
  return [...new Set(Array.from(text.matchAll(/(?:^|[^a-zA-Z0-9])([a-f0-9]{32}\.png)(?=$|[^a-zA-Z0-9.])/g), (match) => match[1]))];
}

export function messageText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((block) => typeof block === "string" ? block : typeof block?.text === "string" ? block.text : "").filter(Boolean).join("\n");
  return content == null ? "" : String(content);
}

export function renderMarkdown(markdown) {
  if (!markdown) return "";
  const raw = String(markdown).replace(/\r\n/g, "\n");
  const lines = raw.split("\n");
  const out = [];
  let inCodeBlock = false;
  let codeBlockLang = "";
  let codeBlockLines = [];
  let inList = false;
  let listType = "ul";
  let inBlockquote = false;
  let blockquoteLines = [];
  let inTable = false;
  let tableLines = [];

  function closeList() {
    if (inList) {
      out.push(`</${listType}>`);
      inList = false;
    }
  }

  function closeBlockquote() {
    if (inBlockquote) {
      const content = blockquoteLines.map(formatInline).join("<br>");
      out.push(`<blockquote><p>${content}</p></blockquote>`);
      inBlockquote = false;
      blockquoteLines = [];
    }
  }

  function closeTable() {
    if (inTable && tableLines.length) {
      let html = '<div class="table-wrap"><table>';
      const rows = tableLines.map((row) =>
        row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim())
      );
      if (rows.length > 0) {
        html += "<thead><tr>";
        for (const cell of rows[0]) html += `<th>${formatInline(cell)}</th>`;
        html += "</tr></thead>";
      }
      if (rows.length > 2) {
        html += "<tbody>";
        for (let i = 2; i < rows.length; i++) {
          html += "<tr>";
          for (const cell of rows[i]) html += `<td>${formatInline(cell)}</td>`;
          html += "</tr>";
        }
        html += "</tbody>";
      }
      html += "</table></div>";
      out.push(html);
      inTable = false;
      tableLines = [];
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const codeFenceMatch = line.match(/^```([a-zA-Z0-9_-]*)/);
    if (codeFenceMatch && !inCodeBlock) {
      closeList();
      closeBlockquote();
      closeTable();
      inCodeBlock = true;
      codeBlockLang = codeFenceMatch[1] || "";
      codeBlockLines = [];
      continue;
    } else if (line.startsWith("```") && inCodeBlock) {
      inCodeBlock = false;
      const codeText = codeBlockLines.join("\n");
      const escapedCode = escapeHtml(codeText);
      const displayLang = codeBlockLang ? escapeHtml(codeBlockLang) : "kod";
      out.push(
        `<div class="code-block" data-lang="${escapeHtml(codeBlockLang)}">` +
          `<div class="code-block-header">` +
            `<span class="code-lang">${displayLang}</span>` +
            `<button class="code-copy-btn" type="button" aria-label="Kopiuj kod">` +
              `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" fill="none" stroke-width="1.8"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke="currentColor" fill="none" stroke-width="1.8"/></svg>` +
              `<span>Kopiuj</span>` +
            `</button>` +
          `</div>` +
          `<pre><code>${escapedCode}</code></pre>` +
        `</div>`
      );
      codeBlockLines = [];
      codeBlockLang = "";
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    const tableRow = line.trim().startsWith("|") && line.trim().endsWith("|");
    const tableSeparator = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
    if (tableRow && (inTable || tableSeparator.test(lines[i + 1] || ""))) {
      closeList();
      closeBlockquote();
      inTable = true;
      tableLines.push(line);
      continue;
    } else if (inTable) {
      closeTable();
    }

    if (line.startsWith("> ") || line === ">") {
      closeList();
      closeTable();
      inBlockquote = true;
      blockquoteLines.push(line.replace(/^>\s?/, ""));
      continue;
    } else if (inBlockquote) {
      closeBlockquote();
    }

    const ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
    if (ulMatch) {
      closeBlockquote();
      closeTable();
      if (!inList || listType !== "ul") {
        closeList();
        inList = true;
        listType = "ul";
        out.push("<ul>");
      }
      out.push(`<li>${formatInline(ulMatch[2])}</li>`);
      continue;
    }

    const olMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);
    if (olMatch) {
      closeBlockquote();
      closeTable();
      if (!inList || listType !== "ol") {
        closeList();
        inList = true;
        listType = "ol";
        out.push("<ol>");
      }
      out.push(`<li>${formatInline(olMatch[2])}</li>`);
      continue;
    }

    closeList();

    if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
      out.push("<hr>");
      continue;
    }

    const h3Match = line.match(/^###\s+(.*)$/);
    if (h3Match) {
      out.push(`<h3>${formatInline(h3Match[1])}</h3>`);
      continue;
    }
    const h2Match = line.match(/^##\s+(.*)$/);
    if (h2Match) {
      out.push(`<h2>${formatInline(h2Match[1])}</h2>`);
      continue;
    }
    const h1Match = line.match(/^#\s+(.*)$/);
    if (h1Match) {
      out.push(`<h1>${formatInline(h1Match[1])}</h1>`);
      continue;
    }

    if (!line.trim()) continue;

    out.push(`<p>${formatInline(line)}</p>`);
  }

  if (inCodeBlock) {
    const codeText = codeBlockLines.join("\n");
    const escapedCode = escapeHtml(codeText);
    const displayLang = codeBlockLang ? escapeHtml(codeBlockLang) : "kod";
    out.push(
      `<div class="code-block is-streaming" data-lang="${escapeHtml(codeBlockLang)}">` +
        `<div class="code-block-header">` +
          `<span class="code-lang">${displayLang}</span>` +
        `</div>` +
        `<pre><code>${escapedCode}</code></pre>` +
      `</div>`
    );
  }
  closeList();
  closeBlockquote();
  closeTable();

  return out.join("");
}

function bindCodeCopyButtons(container) {
  for (const button of container.querySelectorAll(".code-copy-btn")) {
    if (button.dataset.bound) continue;
    button.dataset.bound = "true";
    button.addEventListener("click", async () => {
      const codeBlock = button.closest(".code-block");
      const code = codeBlock?.querySelector("pre code")?.textContent || "";
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code);
        const originalText = button.querySelector("span")?.textContent || "Kopiuj";
        button.querySelector("span").textContent = "Skopiowano!";
        setTimeout(() => {
          if (button.querySelector("span")) button.querySelector("span").textContent = originalText;
        }, 2000);
      } catch {
        showToast("Nie udało się skopiować kodu do schowka.", "error");
      }
    });
  }
}

function applyTheme(theme, { persist = true } = {}) {
  state.theme = theme;
  if (persist) storage.set("platon.theme", theme);
  if (typeof document !== "undefined") {
    if (theme === "system") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = theme;
    }
  }
  const radio = $(`input[name="app-theme"][value="${theme}"]`);
  if (radio) radio.checked = true;
}

function setConnection(connected, text, kind = "") {
  elements.connection.classList.remove("is-offline", "is-online", "is-busy");
  if (kind === "busy") {
    elements.connection.classList.add("is-busy");
  } else if (connected) {
    elements.connection.classList.add("is-online");
  } else {
    elements.connection.classList.add("is-offline");
  }
  elements.connectionLabel.textContent = text;
}

function showToast(message, kind = "info") {
  const region = $("#toast-region");
  if (!region) return;
  clearTimeout(state.toastTimer);
  region.replaceChildren();
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.textContent = message;
  region.append(toast);
  state.toastTimer = window.setTimeout(() => toast.remove(), 4800);
}

function friendlyError(error) {
  if (error instanceof ApiError) {
    if (error.status === 0) return error.message;
    return error.message || `Błąd backendu (${error.status}).`;
  }
  return error?.message || "Wystąpił nieoczekiwany błąd.";
}

function setStatus(text = "", kind = "") {
  elements.status.textContent = text;
  elements.status.className = `composer-status${kind ? ` status-${kind}` : ""}`;
}

function activeThreadId() {
  return state.snapshot?.thread_id || null;
}

function currentThread() {
  return state.threads.find((item) => item.thread_id === activeThreadId());
}

function syncControls() {
  const interrupts = state.snapshot?.interrupts || [];
  const pending = interrupts.length > 0;
  const canRetry = Boolean(state.snapshot?.can_retry);
  const unavailable = state.busy || state.backendBusy || state.switching;
  const locked = unavailable || !state.snapshot || pending;
  elements.input.disabled = locked;
  elements.send.disabled = locked || !elements.input.value.trim();
  elements.attach.disabled = locked;
  if (elements.attachImage) elements.attachImage.disabled = locked;
  elements.stop.hidden = !state.busy && !state.backendBusy;
  elements.stop.disabled = (!state.busy && !state.backendBusy) || state.stopRequested;
  elements.retry.hidden = state.busy || !canRetry || pending;
  elements.discard.hidden = state.busy || (!canRetry && !pending);
  $("#new-chat").disabled = unavailable || !state.config;
  $("#open-images").disabled = unavailable || !state.snapshot;
  $("#thread-menu-button").disabled = unavailable || !activeThreadId();
  for (const button of elements.threadList.querySelectorAll("button")) button.disabled = unavailable;
  if (elements.exportChatButton) elements.exportChatButton.disabled = state.busy || !state.snapshot?.messages?.length;
  elements.modelPill.lastElementChild.textContent = state.config?.agent_config?.model_name || "Agent lokalny";
  elements.modelPill.title = state.config?.orchestrator_config?.base_url || "Agent lokalny";
  renderAttachments();
  if (!unavailable && state.imageGalleryPending && elements.imageDialog.open) void showImages();
}

function updateThreadTitle() {
  const thread = currentThread();
  const message = state.snapshot?.messages?.find((item) => item.role === "user")?.content;
  const fallback = message ? String(message).split(/\s+/).slice(0, 7).join(" ") : "Nowa rozmowa";
  elements.title.textContent = thread?.title || fallback;
}

function setThreadList(threads) {
  state.threads = Array.isArray(threads) ? threads : [];
  elements.threadList.replaceChildren();
  const query = (state.threadSearchQuery || "").trim().toLowerCase();
  const filtered = query
    ? state.threads.filter((t) => (t.title || "").toLowerCase().includes(query) || (t.thread_id || "").toLowerCase().includes(query))
    : state.threads;

  if (!filtered.length) {
    const empty = document.createElement("p");
    empty.className = "thread-empty";
    empty.textContent = query ? "Brak rozmów pasujących do wyszukiwania." : "Twoje rozmowy pojawią się tutaj.";
    elements.threadList.append(empty);
    return;
  }
  for (const thread of filtered) {
    const row = document.createElement("div");
    row.className = "thread-row";
    row.classList.toggle("is-active", thread.thread_id === activeThreadId());
    const open = document.createElement("button");
    open.className = "thread-open";
    open.type = "button";
    open.textContent = thread.title || "Rozmowa bez tytułu";
    open.title = thread.title || thread.thread_id;
    open.setAttribute("aria-current", thread.thread_id === activeThreadId() ? "page" : "false");
    open.disabled = state.busy;
    open.addEventListener("click", () => selectThread(thread.thread_id));
    const remove = document.createElement("button");
    remove.className = "thread-delete";
    remove.type = "button";
    remove.title = "Usuń rozmowę";
    remove.setAttribute("aria-label", `Usuń rozmowę: ${thread.title || "bez tytułu"}`);
    remove.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M10 11v6m4-6v6M7 7l1 13h8l1-13M9 7V4h6v3"/></svg>';
    remove.disabled = state.busy;
    remove.addEventListener("click", () => removeThread(thread.thread_id));
    row.append(open, remove);
    elements.threadList.append(row);
  }
}

function isNearBottom() {
  const scroll = elements.conversationScroll;
  return scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 160;
}

function scrollToBottom() {
  elements.conversationScroll.scrollTop = elements.conversationScroll.scrollHeight;
}

function appendGeneratedImages(body, filenames) {
  for (const filename of [...new Set(filenames)]) {
    if (body.querySelector(`img[src="${imageUrl(filename)}"]`)) continue;
    const figure = document.createElement("figure");
    figure.className = "generated-image";
    const link = document.createElement("a");
    link.className = "generated-image-preview";
    link.href = imageUrl(filename);
    const image = document.createElement("img");
    image.src = imageUrl(filename);
    image.alt = "Wygenerowany obraz";
    image.loading = "lazy";
    image.addEventListener("load", () => {
      const scroll = elements.conversationScroll;
      if (scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < image.height + 160) scrollToBottom();
    });
    image.addEventListener("error", () => { image.alt = "Nie udało się wczytać obrazu."; });
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const dialog = document.createElement("dialog");
      dialog.className = "image-preview-dialog";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "secondary-button";
      close.textContent = "Zamknij podgląd";
      close.addEventListener("click", () => dialog.close());
      const full = document.createElement("img");
      full.src = imageUrl(filename);
      full.alt = image.alt;
      dialog.append(close, full);
      dialog.addEventListener("close", () => dialog.remove(), { once: true });
      document.body.append(dialog);
      dialog.showModal();
      close.focus();
    });
    link.append(image);
    const caption = document.createElement("figcaption");
    const download = document.createElement("a");
    download.className = "image-action";
    download.href = imageUrl(filename, true);
    download.download = filename;
    download.textContent = "Pobierz";
    caption.append(download);
    figure.append(link, caption);
    body.append(figure);
  }
}

function rememberGeneratedImages(filenames, messages = [], thread = activeThreadId()) {
  filenames = filenames.flatMap(generatedImageFilenames);
  if (!filenames.length) return;
  const index = messages.findLastIndex((item) => item.role === "assistant");
  const lastUser = messages.findLastIndex((item) => item.role === "user");
  if (!thread) return;
  const entries = state.generatedImages[thread] ||= {};
  const messageIndex = index <= lastUser ? messages.length : index;
  entries[messageIndex] = [...new Set([...(entries[messageIndex] || []), ...filenames])];
  storage.set("platon.generatedImages", JSON.stringify(state.generatedImages));
}

function textMessage(role, text, options = {}) {
  const article = document.createElement("article");
  article.className = `message message-${role}${options.pending ? " message-pending" : ""}`;
  if (options.id) article.id = options.id;
  if (role !== "user") {
    const avatar = document.createElement("div");
    avatar.className = `message-avatar${role === "system" ? " avatar-system" : ""}`;
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = role === "system" ? "!" : "P";
    article.append(avatar);
  }
  const content = document.createElement("div");
  content.className = "message-content";
  
  const header = document.createElement("div");
  header.className = "message-header";
  if (options.label) {
    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = options.label;
    header.append(label);
  }
  if (options.timestamp || options.pending) {
    const time = document.createElement("span");
    time.className = "message-time";
    const date = options.timestamp ? new Date(options.timestamp) : new Date();
    if (!Number.isNaN(date.getTime())) {
      time.textContent = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
      header.append(time);
    }
  }
  content.append(header);

  const body = document.createElement("div");
  body.className = "message-body";
  if (role === "assistant" && text) {
    body.innerHTML = renderMarkdown(text);
    bindCodeCopyButtons(body);
  } else {
    body.textContent = text || "";
        if (role === "user" && options.sentImages && options.sentImages.length) {
          const imgContainer = document.createElement("div");
          imgContainer.className = "user-sent-images";
          for (const item of options.sentImages) {
            const img = document.createElement("img");
            img.className = "user-sent-image";
            let src;
            let alt = "Zdjęcie";
            if (typeof item === "string") {
              src = item.startsWith("data:") || item.startsWith("blob:") ? item : sentImageUrl(item);
              alt = item;
            } else if (item instanceof File || item instanceof Blob) {
              src = URL.createObjectURL(item);
              alt = item.name || "Zdjęcie";
            } else if (item && typeof item === "object") {
              src = item.src || sentImageUrl(item.filename || item.name || "");
              alt = item.name || item.filename || "Zdjęcie";
            } else {
              src = sentImageUrl(String(item));
            }
            img.alt = alt;
            img.loading = "lazy";
            img.src = src;
            img.addEventListener("click", () => {
              const dialog = document.createElement("dialog");
              dialog.className = "image-preview-dialog";
              const close = document.createElement("button");
              close.type = "button";
              close.className = "secondary-button";
              close.textContent = "Zamknij podgląd";
              close.addEventListener("click", () => dialog.close());
              const full = document.createElement("img");
              full.src = src;
              full.alt = alt;
              dialog.append(close, full);
              dialog.addEventListener("close", () => dialog.remove(), { once: true });
              document.body.append(dialog);
              dialog.showModal();
              close.focus();
            });
            img.addEventListener("error", () => { img.style.display = "none"; });
            imgContainer.append(img);
          }
          body.append(imgContainer);
        }
  }
  if (role === "assistant") appendGeneratedImages(body, [...generatedImageFilenames(text), ...(options.images || [])]);
  content.append(body);

  if (role === "assistant" && text) {
    const actions = document.createElement("div");
    actions.className = "message-actions";
    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "message-action-btn";
    copyBtn.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" stroke-width="1.8"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" stroke-width="1.8"/></svg><span>Kopiuj</span>';
    copyBtn.title = "Kopiuj treść odpowiedzi";
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(text);
        copyBtn.querySelector("span").textContent = "Skopiowano!";
        setTimeout(() => {
          if (copyBtn.querySelector("span")) copyBtn.querySelector("span").textContent = "Kopiuj";
        }, 2000);
      } catch {
        showToast("Nie udało się skopiować wiadomości.", "error");
      }
    });
    actions.append(copyBtn);
    content.append(actions);
  }

  article.append(content);
  elements.conversation.append(article);
  return { article, body };
}

function renderWelcome() {
  elements.conversation.replaceChildren();
  const welcome = document.createElement("section");
  welcome.className = "welcome";
  const mark = document.createElement("div");
  mark.className = "welcome-mark";
  mark.textContent = "p";
  const kicker = document.createElement("span");
  kicker.className = "eyebrow";
  kicker.textContent = "LOKALNY ASYSTENT AI";
  const title = document.createElement("h2");
  title.textContent = "Od czego zaczynamy?";
  const description = document.createElement("p");
  description.textContent = "Porozmawiaj z Platonem o dokumentach, pomysłach albo zadaniu, które masz przed sobą.";
  const suggestions = document.createElement("div");
  suggestions.className = "suggestions";
  const items = [
    ["Odnajdź odpowiedź", "Przeszukaj moje dokumenty i wskaż źródła"],
    ["Uporządkuj pomysł", "Pomóż mi ułożyć plan na najbliższy tydzień"],
    ["Wyjaśnij temat", "Wytłumacz mi trudny temat prostymi słowami"],
  ];
  for (const [titleText, prompt] of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion-card";
    const strong = document.createElement("strong");
    strong.textContent = titleText;
    const small = document.createElement("span");
    small.textContent = prompt;
    button.append(strong, small);
    button.addEventListener("click", () => {
      elements.input.value = prompt;
      resizeInput();
      syncControls();
      elements.input.focus();
    });
    suggestions.append(button);
  }
  welcome.append(mark, kicker, title, description, suggestions);
  elements.conversation.append(welcome);
}

function renderMessages(messages = []) {
  elements.conversation.replaceChildren();
  const visible = Array.isArray(messages) ? messages.filter((message) => ["user", "assistant", "system"].includes(message.role)) : [];
  if (!visible.length) {
    renderWelcome();
    return;
  }
  const savedImages = state.generatedImages?.[activeThreadId()] || {};
  for (const message of visible) {
    const index = messages.indexOf(message);
    if (savedImages[index] && message.role !== "assistant") textMessage("assistant", "", { label: "Platon.ai", images: savedImages[index] });
    textMessage(message.role === "assistant" ? "assistant" : message.role,
      displayMessageContent(message.role, message.content),
      { label: message.role === "user" ? "Ty" : message.role === "assistant" ? "Platon.ai" : "Informacja", images: savedImages[index], sentImages: message.images || [], timestamp: message.created_at || message.timestamp });
  }
  if (savedImages[messages.length]) textMessage("assistant", "", { label: "Platon.ai", images: savedImages[messages.length] });
  scrollToBottom();
}

function addSystemCard(title, message, action = null) {
  const { article, body } = textMessage("system", message, { label: title });
  article.classList.add("message-notice");
  if (action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inline-action";
    button.textContent = action.label;
    button.addEventListener("click", action.onClick);
    body.after(button);
  }
  return article;
}

function renderInterrupts(interrupts = []) {
  $("#interrupt-panel")?.remove();
  const pending = Array.isArray(interrupts) ? interrupts : [];
  if (!pending.length) return;
  const panel = document.createElement("section");
  panel.id = "interrupt-panel";
  panel.className = "interrupt-panel";
  const heading = document.createElement("div");
  heading.className = "interrupt-heading";
  const eyebrow = document.createElement("span");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "POTRZEBNA TWOJA DECYZJA";
  const title = document.createElement("h3");
  title.textContent = "Zanim Platon pójdzie dalej";
  heading.append(eyebrow, title);
  const form = document.createElement("form");
  form.className = "interrupt-form";
  const selections = [];
  for (const interrupt of pending) {
    const value = interrupt.value || {};
    const block = document.createElement("fieldset");
    block.className = "interrupt-block";
    const legend = document.createElement("legend");
    legend.textContent = value.kind === "clarification" ? "Doprecyzowanie" : "Zatwierdź działanie";
    block.append(legend);
    if (value.kind === "clarification") {
      const question = document.createElement("p");
      question.className = "interrupt-question";
      question.textContent = value.question || "Agent potrzebuje dodatkowych informacji.";
      const answer = document.createElement("textarea");
      answer.required = true;
      answer.rows = 2;
      answer.placeholder = "Wpisz odpowiedź…";
      answer.setAttribute("aria-label", "Odpowiedź na pytanie agenta");
      block.append(question, answer);
      selections.push({ id: interrupt.id, answer });
    } else {
      const requests = Array.isArray(value.action_requests) ? value.action_requests : [];
      const choices = [];
      for (const request of requests) {
        const action = document.createElement("div");
        action.className = "review-action";
        const actionName = document.createElement("strong");
        actionName.textContent = request.description || request.name || "Działanie";
        const details = document.createElement("pre");
        details.textContent = typeof request.args === "string" ? request.args : JSON.stringify(request.args ?? {}, null, 2);
        action.append(actionName, details);
        const controls = document.createElement("div");
        controls.className = "review-controls";
        const select = document.createElement("select");
        select.required = true;
        select.setAttribute("aria-label", `Decyzja: ${request.name || request.description || "działanie"}`);
        for (const [valueText, labelText] of [["", "Wybierz decyzję"], ["approve", "Zatwierdź"], ["reject", "Odrzuć"]]) {
          const option = document.createElement("option");
          option.value = valueText;
          option.textContent = labelText;
          select.append(option);
        }
        const feedback = document.createElement("input");
        feedback.type = "text";
        feedback.placeholder = "Informacja zwrotna (opcjonalnie)";
        feedback.setAttribute("aria-label", "Informacja zwrotna do decyzji");
        controls.append(select, feedback);
        action.append(controls);
        block.append(action);
        choices.push({ select, feedback });
      }
      selections.push({ id: interrupt.id, choices });
    }
    form.append(block);
  }
  const footer = document.createElement("div");
  footer.className = "interrupt-footer";
  const hint = document.createElement("span");
  hint.textContent = "Rozmowa pozostanie wstrzymana do czasu odpowiedzi.";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "primary-button";
  submit.textContent = "Odpowiedz i kontynuuj";
  footer.append(hint, submit);
  form.append(footer);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const decisions = Object.fromEntries(selections.map(({ id, choices, answer }) => [
      id,
      answer ? { answer: answer.value.trim() } : {
        decisions: choices.map(({ select, feedback }) => ({ type: select.value, ...(feedback.value.trim() ? { message: feedback.value.trim() } : {}) })),
      },
    ]));
    submit.disabled = true;
    await runStreamOperation(() => resume(decisions), "Wznawiam rozmowę…");
  });
  panel.append(heading, form);
  elements.conversation.append(panel);
  scrollToBottom();
}

function renderOutcome(payload) {
  const canRetry = Boolean(payload?.can_retry);
  if (payload?.status === "error" || payload?.status === "partial") {
    const errors = Array.isArray(payload.errors)
      ? payload.errors.map((item) => typeof item === "string" ? item : item?.message || JSON.stringify(item)).filter(Boolean).join("\n")
      : "Przebieg nie został dokończony.";
    addSystemCard("Nieukończony przebieg", errors || "Przebieg nie został dokończony.", canRetry ? {
      label: "Wznów od zapisanego stanu",
      onClick: () => runStreamOperation(retry, "Wznawiam od zapisanego stanu…"),
    } : null);
  } else if (payload?.status === "stopped") {
    setStatus("Przebieg zatrzymany. Dotychczasowa historia została zachowana.");
  } else if (payload?.status === "completed") {
    setStatus("Odpowiedź gotowa.", "success");
  }
}

function renderDocuments() {
  elements.documentList.replaceChildren();
  const query = (state.documentSearchQuery || "").trim().toLowerCase();
  const filtered = state.documents.filter((record) =>
    (!state.documentCollection || record.collection === state.documentCollection) &&
    (!query || (record.filename || "").toLowerCase().includes(query) || (record.collection || "").toLowerCase().includes(query)));

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty";
    empty.textContent = query || state.documentCollection
      ? "Brak dokumentów pasujących do wyszukiwania."
      : "Nie ma jeszcze dokumentów. Dodaj TXT, PDF lub DOCX, aby korzystać z nich jako źródeł.";
    elements.documentList.append(empty);
  }
  for (const record of filtered) {
    const row = document.createElement("label");
    row.className = "document-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedForAttachment.has(record.id);
    checkbox.disabled = !state.selectedForAttachment.has(record.id) && state.selectedForAttachment.size >= 10;
    checkbox.setAttribute("aria-label", `Użyj w RAG: ${record.filename}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedForAttachment.add(record.id);
      else state.selectedForAttachment.delete(record.id);
      updateAttachmentCount();
      renderDocuments();
    });
    const fileIcon = document.createElement("span");
    fileIcon.className = "file-type";
    fileIcon.textContent = record.filename.split(".").pop()?.toUpperCase() || "DOC";
    const text = document.createElement("span");
    text.className = "document-info";
    const name = document.createElement("strong");
    name.textContent = record.filename;
    const meta = document.createElement("small");
    meta.textContent = `Kolekcja ${record.collection}`;
    text.append(name, meta);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "document-remove";
    remove.textContent = "Usuń";
    remove.setAttribute("aria-label", `Usuń dokument ${record.filename}`);
    remove.addEventListener("click", (event) => {
      event.preventDefault();
      removeDocument(record);
    });
    row.append(checkbox, fileIcon, text, remove);
    elements.documentList.append(row);
  }
  updateAttachmentCount();
}

function updateAttachmentCount() {
  const count = state.selectedForAttachment.size;
  $("#attachment-count").textContent = `${count} wybranych${count >= 10 ? " · limit osiągnięty" : ""}`;
  $("#apply-attachments").disabled = count > 10;
}

function renderAttachments() {
  const selected = state.documents.filter((document) => state.attachments.has(document.id));
  elements.attachmentStrip.replaceChildren();
  elements.attachmentStrip.hidden = selected.length === 0;
  for (const record of selected) {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    chip.title = `Źródło RAG · kolekcja ${record.collection}`;
    const name = document.createElement("span");
    name.textContent = record.filename;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.setAttribute("aria-label", `Odłącz ${record.filename}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      state.attachments.delete(record.id);
      renderAttachments();
    });
    chip.append(name, remove);
    elements.attachmentStrip.append(chip);
  }
}


function renderImageAttachments() {
  const strip = elements.imageAttachmentStrip;
  if (!strip) return;
  strip.replaceChildren();
  strip.hidden = !state.pendingImages.length;
  for (const [index, file] of state.pendingImages.entries()) {
    const chip = document.createElement("div");
    chip.className = "image-attachment-chip";
    const thumb = document.createElement("img");
    thumb.className = "image-attachment-thumb";
    thumb.alt = file.name;
    const url = URL.createObjectURL(file);
    thumb.src = url;
    thumb.addEventListener("load", () => URL.revokeObjectURL(url));
    const name = document.createElement("span");
    name.className = "image-attachment-name";
    name.textContent = file.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "image-attachment-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Usuń ${file.name}`);
    remove.addEventListener("click", () => {
      state.pendingImages.splice(index, 1);
      renderImageAttachments();
      syncControls();
    });
    chip.append(thumb, name, remove);
    strip.append(chip);
  }
}

function renderDocumentCollections() {
  const collections = [...new Set(state.documents.map((record) => record.collection))].sort();
  const filter = $("#document-collection");
  const destination = $("#upload-collection");
  const previous = destination.value || "documents";
  if (state.documentCollection && !collections.includes(state.documentCollection)) state.documentCollection = "";
  for (const [select, values] of [
    [filter, [["", "Wszystkie kolekcje"], ...collections.map((name) => [name, name])]],
    [destination, [...new Set(["documents", ...collections, ...(previous !== "__new__" ? [previous] : [])])].map((name) => [name, name]).concat([["__new__", "Nowa kolekcja…"]])],
  ]) {
    select.replaceChildren();
    for (const [value, label] of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    }
  }
  filter.value = state.documentCollection;
  destination.value = previous;
  syncUploadCollection();
}

function syncUploadCollection() {
  const isNew = $("#upload-collection").value === "__new__";
  $("#new-collection-field").hidden = !isNew;
  $("#collection-name").required = isNew;
  $("#collection-name").disabled = !isNew;
}

function reconcileDocuments() {
  const existing = new Set(state.documents.map((record) => record.id));
  state.attachments = new Set([...state.attachments].filter((id) => existing.has(id)));
  state.selectedForAttachment = new Set([...state.selectedForAttachment].filter((id) => existing.has(id)));
  renderDocumentCollections();
  renderDocuments();
  renderAttachments();
}

async function refreshThreads() {
  try {
    setThreadList(await listThreads());
    updateThreadTitle();
  } catch (error) {
    showToast(`Nie udało się pobrać rozmów: ${friendlyError(error)}`, "error");
  }
}

function renderImages() {
  elements.imageGrid.replaceChildren();
  const query = (state.imageSearchQuery || "").trim().toLowerCase();
  const filtered = query
    ? state.images.filter((img) => (img.filename || "").toLowerCase().includes(query))
    : state.images;

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty image-empty";
    empty.textContent = state.imageGalleryLoading || state.imageGalleryPending ? "Wczytuję obrazy…"
      : state.imageGalleryError ? "Nie udało się wczytać galerii. Kliknij Odśwież."
      : query ? "Brak obrazów pasujących do wyszukiwania." : "Wygenerowane obrazy pojawią się tutaj.";
    elements.imageGrid.append(empty);
    return;
  }
  for (const [index, image] of filtered.entries()) {
    const card = document.createElement("article");
    card.className = "image-card";
    const link = document.createElement("a");
    link.href = imageUrl(image.filename);
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const dialog = document.createElement("dialog");
      dialog.className = "image-preview-dialog";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "secondary-button";
      close.textContent = "Zamknij podgląd";
      close.addEventListener("click", () => dialog.close());
      const full = document.createElement("img");
      full.src = imageUrl(image.filename);
      full.alt = preview.alt;
      dialog.append(close, full);
      dialog.addEventListener("close", () => dialog.remove(), { once: true });
      document.body.append(dialog);
      dialog.showModal();
      close.focus();
    });
    link.setAttribute("aria-label", `Otwórz ${image.filename}`);
    const preview = document.createElement("img");
    preview.src = imageUrl(image.filename);
    preview.alt = `Wygenerowany obraz ${image.filename}`;
    preview.loading = index < 6 ? "eager" : "lazy";
    preview.decoding = "async";
    preview.addEventListener("error", () => {
      preview.alt = "Nie udało się wczytać obrazu. Kliknij Odśwież.";
      card.classList.add("image-load-error");
    });
    link.append(preview);
    const footer = document.createElement("div");
    footer.className = "image-card-footer";
    const info = document.createElement("span");
    info.textContent = `${formatSize(image.size_bytes)} · ${new Date(image.modified_at).toLocaleDateString("pl-PL")}`;
    const controls = document.createElement("span");
    controls.className = "image-actions";
    const download = document.createElement("a");
    download.className = "image-action";
    download.href = imageUrl(image.filename, true);
    download.download = image.filename;
    download.textContent = "Pobierz";
    const remove = document.createElement("button");
    remove.className = "image-action image-delete";
    remove.type = "button";
    remove.textContent = "Usuń";
    remove.addEventListener("click", () => removeImage(image.filename));
    controls.append(download, remove);
    footer.append(info, controls);
    card.append(link, footer);
    elements.imageGrid.append(card);
  }
}

async function showImages() {
  const request = ++state.imageGalleryRequest;
  state.imageGalleryError = "";
  state.imageGalleryPending = Boolean(state.busy || state.backendBusy || state.switching);
  state.imageGalleryLoading = !state.imageGalleryPending;
  openDialog(elements.imageDialog);
  renderImages();
  const status = $("#image-gallery-status");
  const refresh = $("#refresh-images");
  status.textContent = state.imageGalleryPending ? "Galeria odświeży się po zakończeniu zadania." : "Wczytuję obrazy…";
  refresh.disabled = state.imageGalleryLoading || state.imageGalleryPending;
  if (state.imageGalleryPending) return;
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const images = await listImages({ signal: AbortSignal.timeout(10000) });
        if (request !== state.imageGalleryRequest) return;
        state.images = images;
        status.textContent = "";
        break;
      } catch (error) {
        if (request !== state.imageGalleryRequest) return;
        if (attempt === 2 || !(error instanceof TypeError || [409, 502, 503, 504].includes(error.status))) throw error;
        await new Promise(resolve => setTimeout(resolve, 400 * (attempt + 1)));
        if (request !== state.imageGalleryRequest) return;
      }
    }
  } catch (error) {
    if (request !== state.imageGalleryRequest) return;
    state.imageGalleryError = friendlyError(error);
    status.textContent = translateText("Nie udało się pobrać obrazów: ", document.documentElement.lang || "pl") + state.imageGalleryError;
  } finally {
    if (request === state.imageGalleryRequest) {
      state.imageGalleryLoading = false;
      refresh.disabled = false;
      renderImages();
    }
  }
}

async function refreshSnapshot({ quiet = false } = {}) {
  try {
    state.snapshot = await getSnapshot();
    state.backendBusy = false;
    storage.set("platon.activeThreadId", state.snapshot.thread_id);
    renderMessages(state.snapshot.messages);
    renderInterrupts(state.snapshot.interrupts);
    updateThreadTitle();
    await refreshThreads();
    syncControls();
    setConnection(true, "Backend połączony");
    if (state.snapshot.interrupts?.length) setStatus("Oczekuje odpowiedź — formularz znajduje się powyżej.", "warning");
    else if (state.snapshot.can_retry) setStatus("Przebieg można wznowić od ostatniego zapisanego kroku.", "warning");
    else if (!quiet) setStatus("");
    return state.snapshot;
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && error.message === "Agent runtime is busy.") {
      state.backendBusy = true;
      setConnection(true, "Backend zajęty (trwa zadanie)", "busy");
      setStatus("Agent wykonuje zadanie w tle. Możesz je zatrzymać.", "warning");
      syncControls();
      return state.snapshot;
    }
    setConnection(false, "Brak połączenia z backendem");
    throw error;
  }
}

async function initialize(config, { keepMessages = false } = {}) {
  state.switching = true;
  syncControls();
  try {
    state.config = await initializeRuntime(config);
    state.backendBusy = false;
    const snapshot = await getSnapshot();
    state.snapshot = snapshot;
    storage.set("platon.activeThreadId", snapshot.thread_id);
    if (!keepMessages) renderMessages(snapshot.messages);
    renderInterrupts(snapshot.interrupts);
    await refreshThreads();
    updateThreadTitle();
    setConnection(true, "Backend połączony");
    setStatus("");
  } finally {
    state.switching = false;
    syncControls();
  }
}

async function boot() {
  setConnection(false, "Łączenie z backendem…");
  try {
    // Electron's loopback port can change, so its browser storage is only a
    // fallback. Read durable preferences before selecting a conversation.
    for (const key of ["platon.activeThreadId", "platon.theme", "platon.generatedImages"]) {
      try {
        const value = await globalThis.platonWindow?.getPreference?.(key);
        if (value != null) { try { globalThis.localStorage?.setItem(key, value); } catch {} }
      } catch {}
    }
    const theme = storage.get("platon.theme");
    if (["light", "dark", "system"].includes(theme)) applyTheme(theme, { persist: false });
    try {
      const images = JSON.parse(storage.get("platon.generatedImages") || "{}");
      state.generatedImages = images && typeof images === "object" && !Array.isArray(images) ? images : {};
    } catch { state.generatedImages = {}; }
    let snapshot;
    try {
      snapshot = await getSnapshot();
      state.config = await getConfig();
      state.defaultModel = state.config?.agent_config?.model_name || DEFAULT_CONFIG.agent_config.model_name;
      state.backendBusy = false;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        if (error.message === "Agent runtime is busy.") {
          state.backendBusy = true;
          setConnection(true, "Backend zajęty (trwa zadanie)", "busy");
          setStatus("Agent wykonuje zadanie w tle. Możesz je zatrzymać przyciskiem poniżej.", "warning");
          try {
            state.config = await getConfig();
            state.defaultModel = state.config?.agent_config?.model_name || DEFAULT_CONFIG.agent_config.model_name;
          } catch {}
          syncControls();
          return;
        }
        if (error.message === "Initialize the agent runtime first.") {
          const config = structuredClone(DEFAULT_CONFIG);
          // No ID lets the backend reopen its latest stored conversation;
          // a stale local ID would instead create an empty thread.
          state.config = await initializeRuntime(config);
          state.defaultModel = state.config?.agent_config?.model_name || DEFAULT_CONFIG.agent_config.model_name;
          snapshot = await getSnapshot();
          state.backendBusy = false;
        } else {
          throw error;
        }
      } else {
        throw error;
      }
    }
    const threads = await listThreads();
    const savedThreadId = storage.get("platon.activeThreadId");
    const targetThread = threads.find((thread) => thread.thread_id === savedThreadId)
      || [...threads].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))[0];
    const threadModels = getThreadModels();
    const effectiveThreadId = targetThread ? targetThread.thread_id : snapshot.thread_id;
    const modelForThread = (effectiveThreadId && threadModels[effectiveThreadId]) || getDefaultModel();
    if (targetThread && targetThread.thread_id !== snapshot.thread_id) {
      state.config = await initializeRuntime({
        ...structuredClone(state.config),
        thread_id: targetThread.thread_id,
        agent_config: { ...structuredClone(state.config?.agent_config), model_name: modelForThread },
      });
      snapshot = await getSnapshot();
    } else if (effectiveThreadId && state.config?.agent_config?.model_name !== modelForThread) {
      state.config = await initializeRuntime({
        ...structuredClone(state.config),
        thread_id: effectiveThreadId,
        agent_config: { ...structuredClone(state.config?.agent_config), model_name: modelForThread },
      });
      snapshot = await getSnapshot();
    }
    state.snapshot = snapshot;
    storage.set("platon.activeThreadId", snapshot.thread_id);
    renderMessages(snapshot.messages);
    renderInterrupts(snapshot.interrupts);
    await refreshThreads();
    updateThreadTitle();
    syncControls();
    setConnection(true, "Backend połączony");
    if (snapshot.interrupts?.length) setStatus("Oczekuje odpowiedź — formularz znajduje się powyżej.", "warning");
    else if (snapshot.can_retry) setStatus("Przebieg można wznowić od ostatniego zapisanego kroku.", "warning");
  } catch (error) {
    setConnection(false, "Nie udało się połączyć");
    renderWelcome();
    setStatus(friendlyError(error), "error");
    showToast(`Nie udało się uruchomić agenta: ${friendlyError(error)}`, "error");
    $("#open-settings").focus();
  }
}

async function runStreamOperation(operation, statusText) {
  if (state.busy) return;
  state.busy = true;
  state.stopRequested = false;
  setStatus(statusText, "working");
  const streamMessage = textMessage("assistant", "", { label: "Platon.ai", pending: true });
  streamMessage.article.classList.add("message-streaming");
  const spinner = document.createElement("span");
  spinner.className = "typing-indicator";
  spinner.dataset.variant = String(state.loadingAnimationIndex++ % 5);
  spinner.setAttribute("aria-hidden", "true");
  spinner.innerHTML = "<i></i><i></i><i></i>";
  streamMessage.body.append(spinner);
  let result = null;
  let streamedText = "";
  let previousImages;
  let imageGenerated = false;
  const startedAt = Date.now();
  syncControls();
  try {
    // Start discovery in parallel so a slow gallery cannot delay chat.
    previousImages = listImages().then((images) => new Set(images.map((image) => image.filename))).catch(() => null);
    const events = await operation();
    for await (const event of events) {
      if (event.type === "delta") {
        const follow = isNearBottom();
        if (!streamedText) {
          spinner.remove();
          streamMessage.article.querySelector(".message-header").append(spinner);
        }
        streamedText += String(event.data ?? "");
        streamMessage.body.innerHTML = renderMarkdown(streamedText);
        bindCodeCopyButtons(streamMessage.body);
        if (follow) scrollToBottom();
      } else if (event.type === "progress") {
        if (event.data?.tool === "generate_image" && ["completed", "success"].includes(event.data.status)) imageGenerated = true;
        const tool = event.data?.tool ? `Narzędzie: ${event.data.tool}` : "Agent wykonuje zadanie…";
        const phase = event.data?.status ? ` · ${event.data.status}` : "";
        setStatus(`${tool}${phase}`, "working");
      } else if (event.type === "result") {
        result = event.data;
      } else if (event.type === "error") {
        throw new Error(event.data?.message || "Błąd podczas wykonywania zadania.");
      }
    }
    if (!result) throw new Error("Połączenie zakończyło się bez zdarzenia końcowego. Odświeżam historię przed kolejną próbą.");
    state.snapshot = await getSnapshot();
    state.backendBusy = false;
    storage.set("platon.activeThreadId", state.snapshot.thread_id);
    const follow = isNearBottom();
    const previousScrollTop = elements.conversationScroll.scrollTop;
    renderMessages(state.snapshot.messages);
    if (!follow) elements.conversationScroll.scrollTop = previousScrollTop;
    renderInterrupts(state.snapshot.interrupts);
    renderOutcome(result);
    updateThreadTitle();
    await refreshThreads();
    setConnection(true, "Backend połączony");
    const completedSnapshot = state.snapshot;
    Promise.all([previousImages, listImages()]).then(([before, images]) => {
      state.images = images;
      if (elements.imageDialog.open && !state.imageGalleryLoading) renderImages();
      const generated = images.filter((image) => before
        ? !before.has(image.filename)
        : imageGenerated && Date.parse(image.modified_at) >= startedAt - 1000);
      rememberGeneratedImages(generated.map((image) => image.filename), completedSnapshot.messages, completedSnapshot.thread_id);
      if (generated.length && state.snapshot === completedSnapshot && !state.busy && !state.switching) {
        const follow = isNearBottom();
        const scrollTop = elements.conversationScroll.scrollTop;
        renderMessages(state.snapshot.messages);
        renderInterrupts(state.snapshot.interrupts);
        renderOutcome(result);
        if (!follow) elements.conversationScroll.scrollTop = scrollTop;
      }
    }).catch(() => {}); // Gallery failures never discard a completed answer.
  } catch (error) {
    const message = friendlyError(error);
    setStatus("Odświeżam stan rozmowy…", "warning");
    try {
      await refreshSnapshot({ quiet: true });
      addSystemCard("Wystąpił błąd", message);
      setStatus(`Stan rozmowy został odświeżony. ${message}`, "error");
    } catch (refreshError) {
      spinner.remove();
      if (!streamedText) streamMessage.article.remove();
      else streamMessage.article.classList.remove("message-streaming", "message-pending");
      addSystemCard("Wystąpił błąd", message);
      setConnection(false, "Brak połączenia z backendem");
      setStatus(`${message} Nie udało się odświeżyć historii: ${friendlyError(refreshError)}`, "error");
    }
  } finally {
    spinner.remove();
    state.busy = false;
    state.stopRequested = false;
    syncControls();
    elements.input.focus();
  }
}

export function buildRagMessage(message, records) {
  if (!records.length) return message;
  const sources = records.map(({ filename, collection, path }) => ({ filename, collection, ...(path ? { path } : {}) }));
  return `${message}\n\n${RAG_INSTRUCTIONS}${JSON.stringify(sources)}`;
}

export function displayMessageContent(role, content) {
  const text = messageText(content);
  const marker = `\n\n${RAG_INSTRUCTIONS}`;
  const start = text.lastIndexOf(marker);
  if (role !== "user" || start < 0) return text;
  try {
    const records = JSON.parse(text.slice(start + marker.length));
    if (!Array.isArray(records) || !records.length || records.length > 10 ||
        records.some((record) => !record || typeof record.filename !== "string" || typeof record.collection !== "string") ||
        buildRagMessage(text.slice(0, start), records) !== text) return text;
    return `${text.slice(0, start)}\n\nŹródła RAG:\n${records.map((record) => `• ${record.filename} · kolekcja ${record.collection}`).join("\n")}`;
  } catch {
    return text;
  }
}

async function submitMessage(message) {
  const text = message.trim();
  if (!text || state.busy || state.backendBusy || state.switching || !state.snapshot || state.snapshot.interrupts?.length) return;
  const records = state.documents.filter((record) => state.attachments.has(record.id));
  if (records.length !== state.attachments.size) {
    showToast("Wybrany dokument jest niedostępny. Odśwież bibliotekę i wybierz źródła ponownie.", "error");
    return;
  }
  const ragMessage = buildRagMessage(text, records);
  const imagesToSend = Array.isArray(state.pendingImages) ? [...state.pendingImages] : [];
  state.lastSentMessage = text;
  elements.input.value = "";
  resizeInput();
  state.attachments.clear();
  if (Array.isArray(state.pendingImages)) state.pendingImages = [];
  renderAttachments();
  if (typeof renderImageAttachments === "function") renderImageAttachments();
  // Render the pending turn immediately; the final snapshot replaces it.
  if (typeof document !== "undefined") {
    $(".welcome", elements.conversation)?.remove();
    textMessage("user", displayMessageContent("user", ragMessage), { label: "Ty", timestamp: new Date().toISOString(), sentImages: imagesToSend });
    scrollToBottom();
  }
  const sendOp = imagesToSend.length && typeof chatWithImages === "function"
    ? () => chatWithImages(ragMessage, imagesToSend, [])
    : () => chat(ragMessage, []);
  await runStreamOperation(sendOp, "Platon układa odpowiedź…");
}

async function createThread() {
  if (state.busy || state.backendBusy || state.switching || !state.config) return;
  const config = structuredClone(state.config);
  config.thread_id = crypto.randomUUID();
  state.attachments.clear();
  try {
    await initialize(config);
    setStatus("Nowa rozmowa gotowa.", "success");
    elements.input.focus();
  } catch (error) {
    showToast(`Nie udało się utworzyć rozmowy: ${friendlyError(error)}`, "error");
  }
}

async function selectThread(threadId) {
  if (state.busy || state.backendBusy || state.switching || !state.config || threadId === activeThreadId()) return;
  const config = structuredClone(state.config);
  config.thread_id = threadId;
  state.attachments.clear();
  setStatus("Otwieram rozmowę…", "working");
  try {
    await initialize(config);
    setStatus("");
    if (window.matchMedia("(max-width: 760px)").matches) closeSidebar();
  } catch (error) {
    showToast(`Nie udało się otworzyć rozmowy: ${friendlyError(error)}`, "error");
    setStatus(friendlyError(error), "error");
  }
}

async function removeThread(threadId) {
  if (state.busy || state.backendBusy || state.switching || !confirmAction("Usunąć tę rozmowę i jej zapisane punkty kontrolne?")) return;
  const wasCurrent = threadId === activeThreadId();
  try {
    if (wasCurrent) await deleteCurrentThread();
    else await deleteThread(threadId);
    if (wasCurrent) {
      const config = structuredClone(state.config);
      config.thread_id = crypto.randomUUID();
      await initialize(config);
    } else {
      await refreshThreads();
    }
    showToast("Rozmowa została usunięta.", "success");
  } catch (error) {
    showToast(`Nie udało się usunąć rozmowy: ${friendlyError(error)}`, "error");
  }
}

async function stopRun() {
  if (state.stopRequested) return;
  state.stopRequested = true;
  syncControls();
  setStatus("Wysyłam sygnał zatrzymania…", "working");
  try {
    const response = await stop();
    state.backendBusy = false;
    setStatus(response.stopped ? "Agent zatrzymuje bieżący przebieg…" : "Nie ma aktywnego przebiegu do zatrzymania.", "working");
    setTimeout(async () => {
      if (state.busy) return; // The active stream reconciles its own final history.
      try {
        await refreshSnapshot({ quiet: true });
      } catch {}
    }, 1000);
  } catch (error) {
    state.stopRequested = false;
    syncControls();
    showToast(`Nie udało się zatrzymać agenta: ${friendlyError(error)}`, "error");
  }
}

async function discardRun() {
  if (state.busy) return;
  try {
    await discard();
    state.snapshot = await getSnapshot();
    renderMessages(state.snapshot.messages);
    renderInterrupts(state.snapshot.interrupts);
    await refreshThreads();
    syncControls();
    setStatus("Niedokończony przebieg został porzucony.", "success");
  } catch (error) {
    showToast(`Nie udało się porzucić przebiegu: ${friendlyError(error)}`, "error");
  }
}

function exportConversationToMarkdown() {
  if (!state.snapshot?.messages?.length) {
    showToast("Brak wiadomości do wyeksportowania.", "warning");
    return;
  }
  const title = currentThread()?.title || elements.title.textContent || "Rozmowa z Platonem";
  const dateStr = new Date().toLocaleString("pl-PL");
  let md = `# ${title}\n\n_Wyeksportowano: ${dateStr}_\n\n---\n\n`;

  for (const msg of state.snapshot.messages) {
    const role = msg.role === "user" ? "### Ty" : msg.role === "assistant" ? "### Platon" : "### Informacja systemowa";
    md += `${role}\n\n${displayMessageContent(msg.role, msg.content)}\n\n`;
  }

  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const safeFilename = title.replace(/[^a-zA-Z0-9_\-\u00C0-\u017F\s]/g, "").trim().replace(/\s+/g, "_") || "rozmowa";
  a.download = `platon-${safeFilename}.md`;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  showToast("Rozmowa została wyeksportowana do pliku Markdown.", "success");
}

function openDialog(dialog) {
  if (!dialog.open) dialog.showModal();
}

function setSidebarCollapsed(collapsed) {
  state.collapsed = collapsed;
  $("#app-shell").classList.toggle("sidebar-collapsed", collapsed);
  const toggle = $("#sidebar-toggle");
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.setAttribute("aria-label", translateText(collapsed ? "Rozwiń panel" : "Zwiń panel", document.documentElement.lang || "pl"));
  toggle.setAttribute("title", translateText(collapsed ? "Rozwiń panel (Ctrl+B)" : "Zwiń panel (Ctrl+B)", document.documentElement.lang || "pl"));
}

function closeSidebar() {
  elements.sidebar.classList.remove("sidebar-open");
  $("#sidebar-scrim").hidden = true;
}

function confirmAction(message) {
  return window.confirm(translateText(message, document.documentElement.lang || "pl"));
}

function renderResourcePaths(field, input, kind) {
  let paths = field.querySelector(".resource-paths");
  if (!paths) {
    paths = document.createElement("div");
    paths.className = "resource-paths";
    field.append(paths);
  }
  paths.replaceChildren();
  for (const path of [...new Set(input.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))]) {
    const row = document.createElement("div");
    row.className = "resource-path-row";
    const name = document.createElement("code");
    name.textContent = path;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "text-button resource-open";
    button.textContent = "Otwórz";
    button.title = `Otwórz ${path}`;
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      const bridge = globalThis.platonWindow;
      if (!bridge?.openResource) {
        showToast("Otwieranie plików i folderów jest dostępne w aplikacji desktopowej.", "info");
        return;
      }
      button.disabled = true;
      try {
        const backendRoot = $('input[name="backend_root"]', elements.settingsFields)?.value.trim();
        const workingDir = $('input[name="working_dir"]', elements.settingsFields)?.value.trim();
        const result = await bridge.openResource({ kind, path, backendRoot, workingDir });
        if (!result?.ok) throw new Error(result?.error || "Nie udało się otworzyć zasobu.");
      } catch (error) {
        showToast(`Nie udało się otworzyć zasobu: ${friendlyError(error)}`, "error");
      } finally { button.disabled = false; }
    });
    row.append(name, button);
    paths.append(row);
  }
}

function addSettingsField(group, key, value) {
  const field = document.createElement("label");
  field.className = `setting-field${typeof value === "boolean" ? " setting-toggle" : ""}`;
  field.dataset.key = key;
  const title = document.createElement("span");
  title.textContent = fieldLabels[key] || key.replaceAll("_", " ");
  let input;
  if (key === "model_name") {
    input = document.createElement("select");
    input.required = true;
    const option = document.createElement("option");
    option.value = value || "";
    option.textContent = value ? `${value} (bieżący model)` : "Wybierz model…";
    input.append(option);
    input.value = value || "";
  } else if (typeof value === "boolean") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = value;
  } else if (Array.isArray(value)) {
    input = document.createElement("textarea");
    input.rows = Math.max(2, Math.min(4, value.length));
    input.value = value.join("\n");
  } else {
    input = document.createElement("input");
    input.type = typeof value === "number" ? "number" : "text";
    if (key === "model_temperature") {
      input.type = "number";
      input.min = "0";
      input.max = "2";
      input.step = "0.1";
    }
    if (typeof value === "number" && key !== "model_temperature") input.min = "1";
    input.value = value == null ? "" : String(value);
    if (key === "base_url") input.placeholder = "http://127.0.0.1:11434";
    if (key === "sqlite_path") input.placeholder = "Domyślnie w katalogu danych agenta";
  }
  input.name = key;
  input.dataset.valueType = Array.isArray(value) ? "array" : typeof value;
  if (typeof value === "boolean") {
    const toggle = document.createElement("span");
    toggle.className = "toggle-track";
    field.append(title, input, toggle);
  } else {
    field.append(title, input);
  }
  group.append(field);
  if (key === "skills" || key === "memory") {
    renderResourcePaths(field, input, key);
    input.addEventListener("input", () => renderResourcePaths(field, input, key));
  }
  if (key === "model_name") {
    const actions = document.createElement("div");
    actions.className = "model-list-actions";
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.className = "text-button";
    refresh.id = "refresh-ollama-models";
    refresh.textContent = "Odśwież modele";
    refresh.addEventListener("click", () => refreshOllamaModels());
    const hint = document.createElement("span");
    hint.id = "ollama-models-hint";
    hint.className = "form-hint";
    hint.setAttribute("role", "status");
    actions.append(refresh, hint);
    field.append(actions);
  }
  if (key === "base_url") input.addEventListener("change", () => refreshOllamaModels());
}

async function refreshOllamaModels() {
  const requestId = ++state.modelRequest;
  const input = $('select[name="model_name"]', elements.settingsFields);
  const baseUrl = $('input[name="base_url"]', elements.settingsFields).value.trim();
  const hint = $("#ollama-models-hint");
  const refresh = $("#refresh-ollama-models");
  // Invalidate choices from the previous address while the new list is loading.
  input.disabled = true;
  $("#save-settings").disabled = true;
  refresh.disabled = true;
  hint.textContent = "Pobieram modele z Ollama…";
  hint.classList.remove("form-hint-error");
  try {
    const models = await listOllamaModels(baseUrl);
    if (requestId !== state.modelRequest) return;
    const current = input.value;
    input.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = models.length ? "Wybierz model…" : "Brak zainstalowanych modeli";
    input.append(placeholder);
    for (const model of models) {
      const option = document.createElement("option");
      option.value = model;
      option.textContent = model;
      input.append(option);
    }
    input.value = models.includes(current) ? current : "";
    input.disabled = models.length === 0;
    $("#save-settings").disabled = models.length === 0;
    hint.textContent = models.length ? `Dostępne modele: ${models.length}` : "Zainstaluj model w Ollama i odśwież listę.";
  } catch (error) {
    if (requestId !== state.modelRequest) return;
    hint.textContent = `Nie udało się pobrać modeli: ${friendlyError(error)}`;
    hint.classList.add("form-hint-error");
  } finally {
    if (requestId === state.modelRequest) refresh.disabled = false;
  }
}

function renderSettings(config) {
  elements.settingsFields.replaceChildren();
  const sections = [
    ["orchestrator_config", "Połączenie i pamięć", "Backend Ollama, workspace i baza historii."],
    ["agent_config", "Zachowanie agenta", "Model, kontekst oraz dostępne zasoby."],
  ];
  for (const [sectionKey, heading, description] of sections) {
    const section = document.createElement("section");
    section.className = "settings-section";
    section.dataset.section = sectionKey;
    const sectionTitle = document.createElement("h3");
    sectionTitle.textContent = heading;
    const sectionDescription = document.createElement("p");
    sectionDescription.textContent = description;
    const grid = document.createElement("div");
    grid.className = "settings-grid";
    for (const [key, value] of Object.entries(config[sectionKey] || {})) addSettingsField(grid, key, value);
    section.append(sectionTitle, sectionDescription, grid);
    elements.settingsFields.append(section);
  }
}

function readSettings() {
  const result = { orchestrator_config: {}, agent_config: {} };
  for (const input of elements.settingsFields.querySelectorAll("input[name],textarea[name],select[name]")) {
    const parent = input.closest(".settings-section");
    const section = parent.dataset.section;
    const type = input.dataset.valueType;
    let value;
    if (type === "boolean") value = input.checked;
    else if (type === "array") value = input.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    else if (type === "number") value = Number(input.value);
    else value = input.value.trim() || null;
    result[section][input.name] = value;
  }
  return result;
}

async function showSettings() {
  $("#settings-hint").textContent = "";
  $("#settings-hint").classList.remove("form-hint-error");
  const currentThemeRadio = $(`input[name="app-theme"][value="${state.theme}"]`);
  if (currentThemeRadio) currentThemeRadio.checked = true;
  try {
    state.config = await getConfig();
  } catch (error) {
    if (!state.config) state.config = structuredClone(DEFAULT_CONFIG);
    $("#settings-hint").textContent = `Konfiguracja domyślna. ${friendlyError(error)}`;
  }
  renderSettings(state.config);
  openDialog(elements.settingsDialog);
  await refreshOllamaModels();
}


function renderSentImages() {
  const grid = elements.sentImagesGrid;
  if (!grid) return;
  grid.replaceChildren();
  const query = (state.sentImageSearchQuery || "").trim().toLowerCase();
  const filtered = query
    ? (state.sentImages || []).filter((img) => (img.filename || "").toLowerCase().includes(query))
    : (state.sentImages || []);

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty";
    empty.textContent = query
      ? "Brak przesłanych zdjęć pasujących do wyszukiwania."
      : "Nie ma jeszcze przesłanych zdjęć. Dołącz zdjęcia w czacie, a pojawią się tutaj.";
    grid.append(empty);
    return;
  }

  for (const img of filtered) {
    const card = document.createElement("article");
    card.className = "sent-image-card";

    const preview = document.createElement("img");
    preview.className = "sent-image-preview";
    preview.src = sentImageUrl(img.filename);
    preview.alt = img.filename;
    preview.loading = "lazy";
    preview.addEventListener("click", () => {
      const dialog = document.createElement("dialog");
      dialog.className = "image-preview-dialog";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "secondary-button";
      close.textContent = "Zamknij podgląd";
      close.addEventListener("click", () => dialog.close());
      const full = document.createElement("img");
      full.src = sentImageUrl(img.filename);
      full.alt = img.filename;
      dialog.append(close, full);
      dialog.addEventListener("close", () => dialog.remove(), { once: true });
      document.body.append(dialog);
      dialog.showModal();
      close.focus();
    });

    const info = document.createElement("div");
    info.className = "sent-image-info";
    const name = document.createElement("span");
    name.className = "sent-image-name";
    name.textContent = img.filename;
    name.title = img.filename;
    const meta = document.createElement("small");
    const dateStr = img.modified_at ? new Date(img.modified_at).toLocaleDateString("pl-PL") : "";
    meta.textContent = `${formatSize(img.size_bytes)}${dateStr ? ` · ${dateStr}` : ""}`;
    info.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "sent-image-actions";

    const downloadLink = document.createElement("a");
    downloadLink.className = "sent-image-action";
    downloadLink.href = sentImageUrl(img.filename);
    downloadLink.download = img.filename;
    downloadLink.textContent = "Pobierz";

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "sent-image-action delete-action";
    deleteBtn.textContent = "Usuń";
    deleteBtn.addEventListener("click", async () => {
      if (!confirmAction(`Usunąć przesłane zdjęcie „${img.filename}”?`)) return;
      try {
        await deleteSentImage(img.filename);
        state.sentImages = (state.sentImages || []).filter((i) => i.filename !== img.filename);
        renderSentImages();
        showToast("Zdjęcie zostało usunięte.", "success");
      } catch (err) {
        showToast(`Nie udało się usunąć zdjęcia: ${friendlyError(err)}`, "error");
      }
    });

    actions.append(downloadLink, deleteBtn);
    card.append(preview, info, actions);
    grid.append(card);
  }
}

async function loadSentImages() {
  if (!elements.sentImagesGrid) return;
  const status = elements.sentImagesStatus;
  if (status) status.textContent = "Wczytuję przesłane zdjęcia…";
  try {
    state.sentImages = await listSentImages();
    if (status) status.textContent = state.sentImages.length ? `Liczba zdjęć: ${state.sentImages.length}` : "";
    renderSentImages();
  } catch (err) {
    if (status) status.textContent = "Nie udało się pobrać listy zdjęć.";
  }
}

async function showDocuments() {
  state.selectedForAttachment = new Set(state.attachments);
  try {
    state.documents = await listDocuments();
    reconcileDocuments();
    openDialog(elements.documentsDialog);
    loadSentImages().catch(() => {});
  } catch (error) {
    showToast(`Nie udało się pobrać dokumentów: ${friendlyError(error)}`, "error");
  }
}

async function removeDocument(document) {
  if (!confirmAction(`Usunąć „${document.filename}” z katalogu i kolekcji?`)) return;
  try {
    await deleteDocument(document.id);
    state.attachments.delete(document.id);
    state.selectedForAttachment.delete(document.id);
    state.documents = await listDocuments();
    reconcileDocuments();
    showToast("Dokument został usunięty.", "success");
  } catch (error) {
    showToast(`Nie udało się usunąć dokumentu: ${friendlyError(error)}`, "error");
  }
}

function formatSize(bytes) {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function removeImage(filename) {
  if (!confirmAction(`Usunąć obraz ${filename}?`)) return;
  try {
    await deleteImage(filename);
    state.images = await listImages();
    renderImages();
    showToast("Obraz został usunięty.", "success");
  } catch (error) {
    showToast(`Nie udało się usunąć obrazu: ${friendlyError(error)}`, "error");
  }
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 180)}px`;
}

function wireEvents() {
  elements.composerForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage(elements.input.value);
  });
  elements.input.addEventListener("input", () => {
    resizeInput();
    syncControls();
  });
  elements.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!elements.send.disabled) submitMessage(elements.input.value);
    }
    if (event.key === "ArrowUp" && !elements.input.value && state.lastSentMessage) {
      event.preventDefault();
      elements.input.value = state.lastSentMessage;
      resizeInput();
      syncControls();
    }
  });

  if (elements.threadSearch) {
    elements.threadSearch.addEventListener("input", () => {
      state.threadSearchQuery = elements.threadSearch.value;
      setThreadList(state.threads);
    });
  }

  if (elements.documentSearch) {
    elements.documentSearch.addEventListener("input", () => {
      state.documentSearchQuery = elements.documentSearch.value;
      renderDocuments();
    });
  }

  if (elements.imageSearch) {
    elements.imageSearch.addEventListener("input", () => {
      state.imageSearchQuery = elements.imageSearch.value;
      renderImages();
    });
  }

  elements.conversationScroll.addEventListener("scroll", () => {
    const distanceToBottom = elements.conversationScroll.scrollHeight - elements.conversationScroll.clientHeight - elements.conversationScroll.scrollTop;
    if (elements.scrollBottomBtn) {
      elements.scrollBottomBtn.hidden = distanceToBottom < 120;
    }
  });

  if (elements.scrollBottomBtn) {
    elements.scrollBottomBtn.addEventListener("click", () => {
      scrollToBottom();
      elements.scrollBottomBtn.hidden = true;
    });
  }

  if (elements.exportChatButton) {
    elements.exportChatButton.addEventListener("click", exportConversationToMarkdown);
  }

  if (elements.themeToggleButton) {
    elements.themeToggleButton.addEventListener("click", () => {
      const nextTheme = state.theme === "dark" ? "light" : "dark";
      applyTheme(nextTheme);
      showToast(`Przełączono motyw na: ${nextTheme === "dark" ? "ciemny" : "jasny"}.`, "info");
    });
  }

  if (globalThis.platonWindow?.isElectron) {
    $("#win-minimize")?.addEventListener("click", () => globalThis.platonWindow.minimize());
    $("#win-maximize")?.addEventListener("click", () => globalThis.platonWindow.toggleMaximize());
    $("#win-close")?.addEventListener("click", () => globalThis.platonWindow.close());
  } else {
    const controls = $("#window-controls");
    if (controls) controls.style.display = "none";
  }

  for (const radio of document.querySelectorAll('input[name="app-theme"]')) {
    radio.addEventListener("change", (e) => {
      if (e.target.checked) applyTheme(e.target.value);
    });
  }

  $("#new-chat").addEventListener("click", createThread);
  $("#refresh-threads").addEventListener("click", refreshThreads);
  $("#thread-menu-button").addEventListener("click", () => activeThreadId() && removeThread(activeThreadId()));
  elements.stop.addEventListener("click", stopRun);
  elements.retry.addEventListener("click", () => runStreamOperation(retry, "Wznawiam od zapisanego stanu…"));
  elements.discard.addEventListener("click", discardRun);
  elements.attach.addEventListener("click", showDocuments);
  if (elements.tabDocRag) {
    elements.tabDocRag.addEventListener("click", () => {
      elements.tabDocRag.classList.add("is-active");
      elements.tabDocSentImages?.classList.remove("is-active");
      if (elements.docRagPanel) elements.docRagPanel.hidden = false;
      if (elements.docSentImagesPanel) elements.docSentImagesPanel.hidden = true;
    });
  }
  if (elements.tabDocSentImages) {
    elements.tabDocSentImages.addEventListener("click", () => {
      elements.tabDocSentImages.classList.add("is-active");
      elements.tabDocRag?.classList.remove("is-active");
      if (elements.docRagPanel) elements.docRagPanel.hidden = true;
      if (elements.docSentImagesPanel) elements.docSentImagesPanel.hidden = false;
      loadSentImages();
    });
  }
  if (elements.sentImagesSearch) {
    elements.sentImagesSearch.addEventListener("input", () => {
      state.sentImageSearchQuery = elements.sentImagesSearch.value;
      renderSentImages();
    });
  }
  if (elements.refreshSentImages) {
    elements.refreshSentImages.addEventListener("click", () => loadSentImages());
  }
  if (elements.attachImage) {
    elements.attachImage.addEventListener("click", () => elements.imagePicker?.click());
  }
  if (elements.imagePicker) {
    elements.imagePicker.addEventListener("change", () => {
      const files = [...(elements.imagePicker.files || [])];
      elements.imagePicker.value = "";
      const total = state.pendingImages.length + files.length;
      if (total > 4) {
        showToast("Maksymalnie 4 zdjęcia na wiadomość.", "error");
        return;
      }
      for (const file of files) {
        if (file.size > 10 * 1024 * 1024) {
          showToast(`Plik ${file.name} przekracza limit 10 MB.`, "error");
          return;
        }
      }
      state.pendingImages.push(...files);
      renderImageAttachments();
      syncControls();
    });
  }
  $("#document-collection").addEventListener("change", (event) => {
    state.documentCollection = event.target.value;
    renderDocuments();
  });
  $("#upload-collection").addEventListener("change", syncUploadCollection);
  $("#open-documents").addEventListener("click", showDocuments);
  $("#open-images").addEventListener("click", showImages);
  $("#refresh-images").addEventListener("click", showImages);
  $("#open-settings").addEventListener("click", showSettings);

  if (elements.reconnectButton) {
    elements.reconnectButton.addEventListener("click", async (e) => {
      e.stopPropagation();
      setConnection(false, "Ponawiam połączenie…");
      await boot();
    });
  }

  elements.connection.addEventListener("click", async () => {
    setConnection(false, "Ponawiam połączenie…");
    await boot();
  });

  $("#mobile-menu").addEventListener("click", () => {
    setSidebarCollapsed(false);
    elements.sidebar.classList.add("sidebar-open");
    $("#sidebar-scrim").hidden = false;
  });
  $("#sidebar-scrim").addEventListener("click", closeSidebar);
  $("#sidebar-toggle").addEventListener("click", () => {
    if (window.matchMedia("(max-width: 760px)").matches) closeSidebar();
    else {
      setSidebarCollapsed(!state.collapsed);
    }
  });
  for (const button of document.querySelectorAll(".close-dialog")) button.addEventListener("click", () => button.closest("dialog").close());
  $("#refresh-documents").addEventListener("click", async () => {
    try {
      state.documents = await listDocuments();
      reconcileDocuments();
    } catch (error) { showToast(friendlyError(error), "error"); }
  });
  $("#apply-attachments").addEventListener("click", () => {
    if (state.selectedForAttachment.size > 10) return;
    state.attachments = new Set(state.selectedForAttachment);
    renderAttachments();
    elements.documentsDialog.close();
    setStatus(state.attachments.size ? `Wybrano źródła RAG: ${state.attachments.size}.` : "Wyczyszczono źródła RAG.");
  });
  $("#upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("#upload-picker").files?.[0];
    const destination = $("#upload-collection").value;
    const collection = destination === "__new__" ? $("#collection-name").value.trim() : destination;
    if (!file) return;
    if (!/\.(txt|pdf|docx)$/i.test(file.name) || file.size === 0) {
      showToast("Wybierz niepusty plik TXT, PDF lub DOCX.", "error");
      return;
    }
    if (file.size > 100 * 1024 * 1024) {
      showToast("Dokument przekracza limit 100 MiB.", "error");
      return;
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{1,61}[A-Za-z0-9]$/.test(collection)) {
      showToast("Nazwa kolekcji musi mieć 3–63 znaki: litery, cyfry, _ lub -. Pierwszy i ostatni znak musi być literą lub cyfrą.", "error");
      return;
    }
    const button = event.currentTarget.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Indeksuję…";
    try {
      const uploaded = await uploadDocument(file, collection);
      if (uploaded?.id && state.selectedForAttachment.size < 10) state.selectedForAttachment.add(uploaded.id);
      $("#upload-picker").value = "";
      state.documents = await listDocuments();
      state.documentCollection = collection;
      reconcileDocuments();
      $("#upload-collection").value = collection;
      syncUploadCollection();
      showToast(`Dodano dokument „${file.name}”.`, "success");
    } catch (error) {
      showToast(`Nie udało się dodać dokumentu: ${friendlyError(error)}`, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Dodaj dokument";
    }
  });
  elements.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("#save-settings");
    button.disabled = true;
    button.textContent = "Zapisuję…";
    try {
      const result = await updateConfig(readSettings());
      state.config = result;
      state.snapshot = await getSnapshot();
      renderMessages(state.snapshot.messages);
      renderInterrupts(state.snapshot.interrupts);
      await refreshThreads();
      updateThreadTitle();
      syncControls();
      elements.settingsDialog.close();
      showToast("Ustawienia zostały zapisane.", "success");
    } catch (error) {
      $("#settings-hint").textContent = friendlyError(error);
      $("#settings-hint").classList.add("form-hint-error");
    } finally {
      button.disabled = false;
      button.textContent = "Zapisz ustawienia";
    }
  });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      createThread();
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
      event.preventDefault();
      setSidebarCollapsed(!state.collapsed);
    }
    if ((event.metaKey || event.ctrlKey) && (event.key === "," || (event.shiftKey && event.key.toLowerCase() === "s"))) {
      event.preventDefault();
      showSettings();
    }
    if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "d") {
      event.preventDefault();
      showDocuments();
    }
    if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "i") {
      event.preventDefault();
      showImages();
    }
    if (event.key === "Escape") closeSidebar();
  });
}

if (typeof window !== "undefined") {
  applyTheme(state.theme, { persist: false });
  wireEvents();
  renderWelcome();
  boot();
}
