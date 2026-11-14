/** Browser client for the Platon FastAPI backend. */

const API_BASE = (globalThis.PLATON_API_BASE_URL || "/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(status, message, body = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function parseError(response) {
  const raw = await response.text();
  let body = raw;
  try {
    body = raw ? JSON.parse(raw) : null;
  } catch {
    // Keep a plain text response as the error body.
  }
  const detail = body && typeof body === "object" ? body.detail : null;
  const message = typeof detail === "string"
    ? detail
    : detail != null
      ? JSON.stringify(detail)
      : (typeof body === "string" && body) || `${response.status} ${response.statusText}`;
  return new ApiError(response.status, message, body);
}

// These endpoints share one backend lock, including the entire chat stream.
let backendQueue = Promise.resolve();
async function acquireBackend() {
  const previous = backendQueue;
  let release;
  backendQueue = new Promise(resolve => { release = resolve; });
  await previous;
  return release;
}

async function fetchBackend(path, options) {
  for (let attempt = 0; ; attempt++) {
    const response = await fetch(`${API_BASE}${path}`, options);
    if (response.ok) return response;
    const error = await parseError(response);
    // An explicit HTTP rejection means the operation has not started.
    if (attempt >= 2 || error.status !== 409 || error.message !== "Agent runtime is busy.") throw error;
    await new Promise(resolve => setTimeout(resolve, 150 * (attempt + 1)));
  }
}

async function request(path, options = {}) {
  // Stop must reach the active stream immediately, outside its lock/queue.
  const release = path === "/agent-runtime/stop" ? () => {} : await acquireBackend();
  try {
    const response = await fetchBackend(path, options);
    const payload = await response.json();
    return Object.hasOwn(payload ?? {}, "data") ? payload.data : payload;
  } finally { release(); }
}

function jsonOptions(method, value) {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(value),
  };
}

/** Read a backend NDJSON response as an async iterable of event objects. */
async function* stream(path, body, { signal } = {}) {
  const release = await acquireBackend();
  try { yield* readStream(path, body, signal); }
  finally { release(); }
}

async function* readStream(path, body, signal) {
  const response = await fetchBackend(path, {
    ...jsonOptions("POST", body),
    signal,
    headers: { Accept: "application/x-ndjson", "Content-Type": "application/json" },
  });
  if (!response.ok) throw await parseError(response);
  if (!response.body) throw new ApiError(response.status, "Streaming response body is unavailable.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let terminal = false;
  let finished = false;
  function parseEvent(line) {
    const event = JSON.parse(line);
    if (event.type === "result" || event.type === "error") terminal = true;
    return event;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      const lines = pending.split("\n");
      pending = lines.pop();
      for (const line of lines) {
        if (line.trim()) yield parseEvent(line);
      }
      if (done) break;
    }
    if (pending.trim()) yield parseEvent(pending);
    finished = true;
    if (!terminal) throw new ApiError(0, "Połączenie zostało przerwane przed zakończeniem odpowiedzi. Odśwież stan rozmowy.");
  } finally {
    if (!finished) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}


/** Read a backend NDJSON response from a multipart POST as an async iterable. */
async function* streamMultipart(path, formData, { signal } = {}) {
  const release = await acquireBackend();
  try {
    const response = await fetchBackend(path, {
      method: "POST",
      headers: { Accept: "application/x-ndjson" },
      body: formData,
      signal,
    });
    if (!response.ok) throw await parseError(response);
    if (!response.body) throw new ApiError(response.status, "Streaming response body is unavailable.");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    let terminal = false;
    let finished = false;
    function parseEvent(line) {
      const event = JSON.parse(line);
      if (event.type === "result" || event.type === "error") terminal = true;
      return event;
    }
    try {
      while (true) {
        const { value, done } = await reader.read();
        pending += decoder.decode(value, { stream: !done });
        const lines = pending.split("\n");
        pending = lines.pop();
        for (const line of lines) {
          if (line.trim()) yield parseEvent(line);
        }
        if (done) break;
      }
      if (pending.trim()) yield parseEvent(pending);
      finished = true;
      if (!terminal) throw new ApiError(0, "Połączenie zostało przerwane przed zakończeniem odpowiedzi. Odśwież stan rozmowy.");
    } finally {
      if (!finished) await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  } finally { release(); }
}

const runtime = "/agent-runtime";

export const initializeRuntime = (config) => request(`${runtime}/initialize`, jsonOptions("POST", config));
export const getSnapshot = () => request(`${runtime}/snapshot`);
export const getHistory = () => request(`${runtime}/history`);
export const listThreads = () => request(`${runtime}/threads`);
export const deleteThread = (threadId) => request(`${runtime}/threads/${encodeURIComponent(threadId)}`, { method: "DELETE" });
export const deleteCurrentThread = () => request(`${runtime}/threads`, { method: "DELETE" });
export const getConfig = () => request(`${runtime}/config`);
export const updateConfig = (config) => request(`${runtime}/config`, jsonOptions("PUT", config));
/** Installed models from the configured Ollama server (the same list as `ollama list`). */
export async function listOllamaModels(baseUrl = "http://localhost:11434") {
  const params = new URLSearchParams({ base_url: baseUrl });
  const response = await fetch(`/ollama/models?${params}`);
  if (!response.ok) throw await parseError(response);
  const payload = await response.json();
  if (!Array.isArray(payload.models)) throw new ApiError(502, "Ollama zwróciła nieprawidłową listę modeli.");
  return [...new Set(payload.models.map(model => model?.name).filter(name => typeof name === "string" && name.trim()))]
    .sort((a, b) => a.localeCompare(b));
}
export const chat = (message, documentIds = [], options) => stream(`${runtime}/chat`, { message, document_ids: documentIds }, options);
export const chatWithImages = (message, images = [], documentIds = [], options) => {
  if (!images || !images.length) return chat(message, documentIds, options);
  const formData = new FormData();
  formData.append("message", message);
  formData.append("document_ids", JSON.stringify(documentIds));
  for (const file of images) formData.append("images", file);
  return streamMultipart(`${runtime}/chat-with-images`, formData, options);
};
export const sentImageUrl = (filename) => `${API_BASE}/agent-runtime/sent-image/${encodeURIComponent(filename)}`;
export const listSentImages = () => request(`${runtime}/sent-images`);
export const deleteSentImage = (filename) => request(`${runtime}/sent-image/${encodeURIComponent(filename)}`, { method: "DELETE" });
export const resume = (decisions, options) => stream(`${runtime}/resume`, { decisions }, options);
export const retry = (options) => stream(`${runtime}/retry`, {}, options);
export const stop = () => request(`${runtime}/stop`, { method: "POST" });
export const discard = () => request(`${runtime}/discard`, { method: "POST" });

export const listImages = (options = {}) => request("/images", { cache: "no-store", signal: AbortSignal.timeout(10000), ...options });
export const imageUrl = (filename, download = false) => {
  const query = download ? "?download=true" : "";
  return `${API_BASE}/images/${encodeURIComponent(filename)}${query}`;
};
export const deleteImage = (filename) => request(`/images/${encodeURIComponent(filename)}`, { method: "DELETE" });

export const listDocuments = (collection) => {
  const query = collection ? `?collection=${encodeURIComponent(collection)}` : "";
  return request(`/documents${query}`);
};
export const uploadDocument = (file, collection = "documents") => {
  const params = new URLSearchParams({ filename: file.name, collection });
  return request(`/documents?${params}`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
};
export const deleteDocument = (documentId) => request(`/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });

