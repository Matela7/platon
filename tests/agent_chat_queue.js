// Run the actual page script against a small DOM and controlled HTTP streams.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const elements = new Map();
class Element {
  constructor(tag = "div", id = null) {
    this.tagName = tag;
    this.children = [];
    this.events = {};
    this.style = {};
    this.classList = { toggle() { return false; }, contains() { return false; }, remove() {} };
    this.value = "";
    this.textContent = "";
    this.disabled = false;
    if (id) this.id = id;
  }
  set id(value) { this._id = value; elements.set(value, this); }
  get id() { return this._id; }
  get lastElementChild() { return this.children.at(-1); }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren(...children) { this.children.forEach(child => child.remove()); this.children = []; this.append(...children); }
  remove() {
    this.children.forEach(child => child.remove());
    if (this.id) elements.delete(this.id);
    if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this);
  }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute() {}
  focus() {}
  scrollTo() {}
}
for (const id of ["shell", "chat", "chat-form", "prompt", "send", "meta", "history-list", "stop",
  "queue-panel", "queue-list", "queue-count", "resume-queue", "clear-queue", "new-chat", "sidebar-toggle",
  "sidebar-backdrop", "sidebar-close"])
  new Element("div", id);
const document = { getElementById: id => elements.get(id) || null, createElement: tag => new Element(tag),
  addEventListener() {} };
const window = { matchMedia: () => ({ matches: false, addEventListener() {} }) };
const requests = [];
const history = [];
function jsonResponse(value) { return { ok: true, json: async () => structuredClone(value) }; }
function finish(request, status = "completed", interrupts = []) {
  if (request.message) history.push({ role: "user", content: request.message });
  history.push({ role: "assistant", content: status === "stopped" ? "[⏹]" : "wynik" });
  request.resolve({ type: "result", data: { status, messages: structuredClone(history), answer: "wynik",
    errors: [], interrupts, can_retry: false, thread_id: "one" } });
}
async function fetch(url, options = {}) {
  if (url === "/api/conversations") return jsonResponse({ active_thread_id: "one", conversations: [],
    can_retry: false, interrupts: [], running: false });
  if (url === "/api/history") return jsonResponse(history);
  if (url === "/api/stop") {
    finish(requests.at(-1), "stopped");
    return jsonResponse({ stopped: true, running: true });
  }
  const data = JSON.parse(options.body);
  let resolve;
  const event = new Promise(done => { resolve = done; });
  requests.push({ ...data, url, resolve });
  let read = false;
  return { ok: true, body: { getReader: () => ({ read: async () => {
    if (read) return { done: true };
    read = true;
    return { done: false, value: new TextEncoder().encode(JSON.stringify(await event) + "\n") };
  } }) } };
}
const context = vm.createContext({ document, window, fetch, TextDecoder, Uint8Array });
vm.runInContext(fs.readFileSync(0, "utf8"), context);
const state = expression => vm.runInContext(expression, context);
async function until(predicate) {
  for (let attempt = 0; attempt < 500; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  throw new Error("UI did not reach the expected state");
}
async function submit(text) {
  elements.get("prompt").value = text;
  await elements.get("chat-form").events.submit({ preventDefault() {} });
}

(async () => {
  await until(() => state("ready"));
  await submit("pierwsze");
  await until(() => requests.length === 1);
  assert.equal(elements.get("send").disabled, false);
  assert.equal(elements.get("prompt").disabled, false);
  await submit("drugie");
  await submit("trzecie");
  assert.equal(requests.length, 1);
  assert.equal(state("messageQueue.length"), 2);
  finish(requests[0]);
  await until(() => requests.length === 2);
  assert.equal(requests[1].message, "drugie");
  finish(requests[1]);
  await until(() => requests.length === 3);
  assert.equal(requests[2].message, "trzecie");
  finish(requests[2]);
  await until(() => !state("busy"));
  assert.equal(state("messageQueue.length"), 0);
  assert.equal(elements.get("send").disabled, false);

  await submit("wolne zadanie");
  await until(() => requests.length === 4);
  await submit("oczekujące zadanie");
  await elements.get("stop").events.click();
  await until(() => !state("busy"));
  assert.equal(requests.length, 4);
  assert.equal(state("queuePaused"), true);
  assert.equal(state("messageQueue.length"), 1);
  assert.equal(elements.get("resume-queue").hidden, false);
  elements.get("resume-queue").events.click();
  await until(() => requests.length === 5);
  assert.equal(requests[4].message, "oczekujące zadanie");
  finish(requests[4]);
  await until(() => !state("busy"));

  await submit("pytanie wymagające doprecyzowania");
  await until(() => requests.length === 6);
  await submit("zadanie po odpowiedzi");
  finish(requests[5], "interrupted", [{ id: "ask", value: { kind: "clarification", question: "Który plik?" } }]);
  await until(() => !state("busy"));
  assert.equal(requests.length, 6);
  assert.equal(state("pendingReviews.length"), 1);
  const panel = elements.get("reviews");
  const reviewForm = panel.lastElementChild.lastElementChild;
  reviewForm.children[0].lastElementChild.value = "plik.txt";
  const resume = reviewForm.events.submit({ preventDefault() {} });
  await until(() => requests.length === 7);
  assert.equal(requests[6].url, "/api/resume");
  finish(requests[6]);
  await resume;
  await until(() => requests.length === 8);
  assert.equal(requests[7].message, "zadanie po odpowiedzi");
  finish(requests[7]);
  await until(() => !state("busy"));
  assert.equal(state("pendingReviews.length"), 0);
  assert.equal(elements.get("send").disabled, false);

  // Stop with an empty queue must not silently prevent a later new message.
  await submit("zatrzymaj to");
  await until(() => requests.length === 9);
  await elements.get("stop").events.click();
  await until(() => !state("busy"));
  await submit("nowe zadanie po stop");
  await until(() => requests.length === 10);
  finish(requests[9]);
  await until(() => !state("busy"));
  process.stdout.write("FIFO, stop, resume, clarification and subsequent turns: OK\n");
})().catch(error => { console.error(error); process.exitCode = 1; });
