import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { setImmediate } from 'node:timers/promises';
import { ApiError } from './api.js';
import { renderMarkdown, messageText, generatedImageFilenames } from './app.js';
import { translateText } from './i18n.js';

const source = readFileSync(new URL('./app.js', import.meta.url), 'utf8')
  .replace(/^import \{[\s\S]*?\} from "\.\/api\.js";/, '')
  .replace(/^import .* from "\.\/i18n\.js";/m, '')
  .replace(/^export /gm, '')
  .split('if (typeof window !== "undefined") {')[0];

function element(tagName = 'div') {
  const classes = new Set();
  return {
    tagName, children: [], listeners: {}, dataset: {}, attributes: {}, value: '', style: {},
    classList: { add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)), toggle: (name, force) => force ? classes.add(name) : classes.delete(name), contains: name => classes.has(name) },
    setAttribute(name, value) { this.attributes[name] = value; },
    append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } },
    replaceChildren(...children) { this.children = []; this.append(...children); },
    remove() { this.removed = true; if (this.parent) this.parent.children = this.parent.children.filter(item => item !== this); },
    addEventListener(name, handler) { this.listeners[name] = handler; },
    querySelectorAll(selector) {
      return this.children.flatMap(child => [child, ...child.querySelectorAll('*')]).filter(child => {
        if (selector === '*') return true;
        if (selector.startsWith('.')) return child.className?.split(' ').includes(selector.slice(1));
        if (selector.startsWith('img[src=')) return child.tagName === 'img' && child.src === selector.slice(9, -2);
        return child.tagName === selector;
      });
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    focus() {}, showModal() { this.open = true; }, close() { this.open = false; this.listeners.close?.(); },
    lastElementChild: { textContent: '' }, scrollHeight: 400, scrollTop: 0, clientHeight: 300,
  };
}

function harness(overrides = {}, saved = {}) {
  const nodes = new Map();
  const document = {
    documentElement: element('html'), body: element('body'), createElement: element,
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, element(selector.startsWith('#') ? 'div' : selector));
      return nodes.get(selector);
    },
  };
  const preferences = new Map(Object.entries(saved));
  const snapshots = { thread_id: 'current', messages: [], interrupts: [] };
  const context = vm.createContext({
    console, ApiError, AbortSignal, document, translateText, structuredClone, crypto: { randomUUID: () => 'new-thread' },
    localStorage: { getItem: key => preferences.get(key) ?? null, setItem: (key, value) => preferences.set(key, value) },
    setTimeout() { return 0; }, clearTimeout() {},
    window: { setTimeout() { return 0; }, matchMedia: () => ({ matches: false }) },
    getSnapshot: async () => snapshots, getConfig: async () => ({ agent_config: {}, orchestrator_config: {} }),
    listThreads: async () => [], listImages: async () => [], initializeRuntime: async config => config,
    imageUrl: (filename, download = false) => `/api/v1/images/${encodeURIComponent(filename)}${download ? '?download=true' : ''}`,
    ...overrides,
  });
  vm.runInContext(source, context);
  return { context, nodes, preferences, run: code => vm.runInContext(code, context), document };
}

test('sidebar can collapse and expand again with matching accessible control state', () => {
  const h = harness();
  h.run('setSidebarCollapsed(true)');
  assert.equal(h.nodes.get('#app-shell').classList.contains('sidebar-collapsed'), true);
  assert.equal(h.nodes.get('#sidebar-toggle').attributes['aria-label'], 'Rozwiń panel');
  assert.equal(h.nodes.get('#sidebar-toggle').attributes['aria-expanded'], 'false');
  h.run('setSidebarCollapsed(false)');
  assert.equal(h.nodes.get('#app-shell').classList.contains('sidebar-collapsed'), false);
  assert.equal(h.nodes.get('#sidebar-toggle').attributes['aria-label'], 'Zwiń panel');
  assert.equal(h.nodes.get('#sidebar-toggle').attributes['aria-expanded'], 'true');
});

test('gallery opens immediately, keeps cached images, and ignores outdated list responses', async () => {
  const pending = [];
  const h = harness({ listImages: () => new Promise(resolve => pending.push(resolve)) });
  h.run('state.images=[{filename:"cached.png",size_bytes:1,modified_at:"2026-11-14"}]');
  const first = h.run('showImages()');
  assert.equal(h.run('elements.imageDialog.open'), true);
  assert.equal(h.run('state.imageGalleryLoading'), true);
  assert.equal(h.run('elements.imageGrid.children[0].children[0].children[0].loading'), 'eager');
  const second = h.run('showImages()');
  pending[1]([{ filename: 'new.png', size_bytes: 1, modified_at: '2026-11-14' }]);
  await second;
  pending[0]([]);
  await first;
  assert.equal(h.run('state.images[0].filename'), 'new.png');
  assert.equal(h.run('state.imageGalleryLoading'), false);
});

test('gallery retries transient busy responses and exposes a persistent refresh action on failure', async () => {
  let attempts = 0;
  const h = harness({
    setTimeout: callback => Promise.resolve().then(callback),
    listImages: async () => {
      if (++attempts < 3) throw new ApiError(409, 'Agent runtime is busy.');
      return [];
    },
  });
  await h.run('showImages()');
  assert.equal(attempts, 3);
  assert.equal(h.run('state.imageGalleryError'), '');
  h.context.listImages = async () => { throw new ApiError(500, 'Disk unavailable'); };
  await h.run('showImages()');
  assert.match(h.nodes.get('#image-gallery-status').textContent, /Disk unavailable/);
  assert.equal(h.nodes.get('#refresh-images').disabled, false);
  assert.match(h.run('elements.imageGrid.children[0].textContent'), /Odśwież/);
});

test('gallery opened during a run waits and refreshes automatically when controls unlock', async () => {
  let calls = 0;
  const h = harness({ listImages: async () => { calls++; return []; } });
  h.run('state.busy=true');
  await h.run('showImages()');
  assert.equal(calls, 0);
  assert.equal(h.run('state.imageGalleryPending'), true);
  h.run('state.busy=false; syncControls()');
  await setImmediate();
  assert.equal(calls, 1);
  assert.equal(h.run('state.imageGalleryPending'), false);
  assert.equal(h.run('state.imageGalleryLoading'), false);
});

test('startup restores durable selected conversation after loopback origin changes', async () => {
  let active = 'empty-runtime';
  const initialized = [];
  const h = harness({
    platonWindow: { getPreference: async key => key === 'platon.activeThreadId' ? 'selected' : null, setPreference: async () => ({ ok: true }) },
    getSnapshot: async () => ({ thread_id: active, messages: [{ role: 'user', content: active }], interrupts: [] }),
    listThreads: async () => [{ thread_id: 'newest', updated_at: '2026-11-14' }, { thread_id: 'selected', updated_at: '2026-11-13' }],
    initializeRuntime: async config => { initialized.push(config); active = config.thread_id; return config; },
  });
  await h.run('boot()');
  assert.equal(initialized.length, 1);
  assert.equal(initialized[0].thread_id, 'selected');
  assert.equal(h.run('state.snapshot.thread_id'), 'selected');
  assert.equal(h.preferences.get('platon.activeThreadId'), 'selected');
});

test('initial theme rendering does not overwrite durable preference before startup reads it', async () => {
  const writes = [];
  const h = harness({ platonWindow: {
    getPreference: async key => key === 'platon.theme' ? 'dark' : null,
    setPreference: async (key, value) => { writes.push([key, value]); return { ok: true }; },
  } });
  h.run('applyTheme(state.theme, { persist: false })');
  await h.run('boot()');
  assert.equal(h.run('state.theme'), 'dark');
  assert.equal(h.document.documentElement.dataset.theme, 'dark');
  assert.equal(writes.some(([key]) => key === 'platon.theme'), false);
  h.run('applyTheme("light")');
  assert.ok(writes.some(([key, value]) => key === 'platon.theme' && value === 'light'));
});

test('stale or absent preference restores newest existing conversation without creating stale ID', async () => {
  let active = 'empty-runtime';
  const initialized = [];
  const h = harness({
    getSnapshot: async () => ({ thread_id: active, messages: [] }),
    listThreads: async () => [{ thread_id: 'older', updated_at: '2026-11-12' }, { thread_id: 'latest', updated_at: '2026-11-14' }],
    initializeRuntime: async config => { initialized.push(config.thread_id); active = config.thread_id; return config; },
  }, { 'platon.activeThreadId': 'deleted-thread' });
  await h.run('boot()');
  assert.deepEqual(initialized, ['latest']);
  assert.equal(h.run('state.snapshot.thread_id'), 'latest');
});

test('cold startup lets backend restore history, and first run keeps one initial conversation', async () => {
  for (const hasHistory of [false, true]) {
    let initialized = false;
    const configs = [];
    const h = harness({
      getSnapshot: async () => {
        if (!initialized) throw new ApiError(409, 'Initialize the agent runtime first.');
        return { thread_id: hasHistory ? 'latest' : 'first', messages: [] };
      },
      initializeRuntime: async config => { configs.push(config); initialized = true; return config; },
      listThreads: async () => hasHistory ? [{ thread_id: 'latest' }] : [],
    }, { 'platon.activeThreadId': 'stale' });
    await h.run('boot()');
    assert.equal(configs.length, 1);
    assert.equal(configs[0].thread_id, undefined);
    assert.equal(h.run('state.snapshot.thread_id'), hasHistory ? 'latest' : 'first');
  }
});

test('pending user turn is visible during generation and replaced once by final snapshot', async () => {
  let h;
  h = harness({
    chat: async function* () {
      assert.equal(h.run('elements.conversation.children.filter(item => item.className === "message message-user").length'), 1);
      assert.equal(h.run('elements.conversation.querySelector(".welcome")'), null);
      yield { type: 'delta', data: '**Done**' };
      yield { type: 'result', data: { status: 'completed' } };
    },
    getSnapshot: async () => ({ thread_id: 'current', messages: [{ role: 'user', content: 'Hello' }, { role: 'assistant', content: '**Done**' }] }),
  });
  h.run('state.snapshot = {thread_id:"current", messages:[]}; renderWelcome()');
  await h.run('submitMessage("Hello")');
  assert.equal(h.run('elements.conversation.children.length'), 2);
  assert.equal(h.run('state.busy'), false);
  assert.match(h.run('elements.conversation.children[1].querySelector(".message-body").innerHTML'), /<strong>Done<\/strong>/);
});

test('loading animations vary between runs, stay while writing, and disappear on completion', async () => {
  const h = harness();
  const variants = [];
  for (let index = 0; index < 2; index++) {
    let indicator;
    h.context.operation = async function* () {
      indicator = h.run('elements.conversation.querySelector(".typing-indicator")');
      variants.push(indicator.dataset.variant);
      yield { type: 'delta', data: 'Answer' };
      assert.ok(h.run('elements.conversation.querySelector(".message-header .typing-indicator")') || indicator.parent.className === 'message-header');
      yield { type: 'result', data: { status: 'completed' } };
    };
    await h.run('runStreamOperation(operation,"Working")');
    assert.equal(indicator.removed, true);
    assert.equal(h.run('elements.conversation.querySelector(".typing-indicator")'), null);
  }
  assert.notEqual(variants[0], variants[1]);
});

test('stream failure retains partial answer when recovery fails and retains notice after successful recovery', async () => {
  for (const recoveryFails of [false, true]) {
    const h = harness({ getSnapshot: async () => {
      if (recoveryFails) throw new Error('offline');
      return { thread_id: 'current', messages: [{ role: 'user', content: 'Hello' }] };
    } });
    h.run('state.snapshot = {thread_id:"current", messages:[]};');
    h.context.operation = async function* () { yield { type: 'delta', data: 'Partial answer' }; throw new Error('Connection lost'); };
    await h.run('runStreamOperation(operation, "Working")');
    const bodies = h.run('elements.conversation.querySelectorAll(".message-body")');
    assert.ok(bodies.some(body => body.textContent === 'Connection lost'));
    if (recoveryFails) assert.ok(bodies.some(body => body.innerHTML?.includes('Partial answer')));
    assert.equal(h.run('state.busy'), false);
    assert.equal(h.run('elements.input.disabled'), false);
  }
});

test('successful image tool renders inline, downloads via backend, and survives preference reload', async () => {
  const filename = 'a'.repeat(32) + '.png';
  const saved = {};
  const h = harness({ platonWindow: { setPreference: async (key, value) => { saved[key] = value; return { ok: true }; } } });
  h.context.filenames = [filename];
  h.run('state.snapshot = {thread_id:"current",messages:[{role:"user",content:"Draw a cat"},{role:"assistant",content:"Here it is"}]}; rememberGeneratedImages(filenames, state.snapshot.messages); renderMessages(state.snapshot.messages);');
  const figure = h.run('elements.conversation.querySelector(".generated-image")');
  assert.equal(figure.children[0].children[0].src, `/api/v1/images/${filename}`);
  assert.equal(figure.children[1].children[0].href, `/api/v1/images/${filename}?download=true`);
  figure.children[0].listeners.click({ preventDefault() {} });
  assert.equal(h.document.body.children[0].open, true);
  assert.ok(saved['platon.generatedImages']);
  const restored = harness({
    platonWindow: { getPreference: async key => saved[key] ?? null },
    getSnapshot: async () => ({ thread_id: 'current', messages: [{ role: 'user', content: 'Draw a cat' }, { role: 'assistant', content: 'Here it is' }] }),
  });
  await restored.run('boot()');
  assert.equal(restored.run('elements.conversation.querySelector(".generated-image").children[0].children[0].src'), `/api/v1/images/${filename}`);
});

test('real stripped terminal event discovers images without delaying completed or interrupted chat', async () => {
  for (const status of ['completed', 'interrupted']) {
    const filename = 'b'.repeat(32) + '.png';
    let finishBaseline;
    let requests = 0;
    const messages = [{ role: 'user', content: 'Generate an image' }];
    if (status === 'completed') messages.push({ role: 'assistant', content: 'Here it is' });
    const h = harness({
      listImages: async () => ++requests === 1 ? new Promise(resolve => { finishBaseline = resolve; }) : [{ filename }],
      getSnapshot: async () => ({ thread_id: 'current', messages, interrupts: [] }),
    });
    h.run('state.snapshot={thread_id:"current",messages:[]}');
    h.context.operation = async function* () {
      yield { type: 'progress', data: { tool: 'generate_image', status: 'completed' } };
      yield { type: 'result', data: { status, answer: status === 'completed' ? 'Here it is' : '', interrupts: [] } };
    };
    await h.run('runStreamOperation(operation,"Generating")');
    assert.equal(h.run('state.busy'), false);
    assert.equal(h.run('elements.conversation.children.length'), messages.length);
    finishBaseline([]);
    await setImmediate();
    assert.equal(h.run('elements.conversation.querySelector(".generated-image").children[0].children[0].src'), `/api/v1/images/${filename}`);
    assert.equal(h.run('state.generatedImages.current[1][0]'), filename);
  }
});

test('stream and final snapshot preserve manual scroll position while reading older messages', async () => {
  const h = harness({ getSnapshot: async () => ({ thread_id: 'current', messages: [{ role: 'assistant', content: 'Final' }] }) });
  h.run('state.snapshot={thread_id:"current",messages:[]}; elements.conversationScroll.scrollHeight=2000; elements.conversationScroll.scrollTop=0');
  h.context.operation = async function* () {
    yield { type: 'delta', data: 'New answer' };
    assert.equal(h.run('elements.conversationScroll.scrollTop'), 0);
    yield { type: 'result', data: { status: 'completed' } };
  };
  await h.run('runStreamOperation(operation,"Working")');
  assert.equal(h.run('elements.conversationScroll.scrollTop'), 0);
});

test('history images and content blocks render safely, markdown preserves code and query strings', () => {
  const filename = 'f'.repeat(32) + '.png';
  assert.deepEqual(generatedImageFilenames(`images/${filename}; ../bad.png; ${filename}`), [filename]);
  assert.deepEqual(generatedImageFilenames('a'.repeat(33) + '.png'), []);
  assert.equal(messageText([{ type: 'text', text: 'One' }, { type: 'text', text: 'Two' }, { type: 'image', url: 'x' }]), 'One\nTwo');
  assert.match(renderMarkdown('`**literal** _value_`'), /<code class="inline-code">\*\*literal\*\* _value_<\/code>/);
  assert.match(renderMarkdown('[link](https://example.com/a_b?x=1&y=2)'), /href="https:\/\/example.com\/a_b\?x=1&amp;y=2"/);
  assert.doesNotMatch(renderMarkdown('[link](https://example.com/?x=1&y=2)'), /&amp;amp;/);
  assert.match(renderMarkdown('| ordinary text |'), /<p>\| ordinary text \|<\/p>/);
  assert.match(renderMarkdown('| A | B |\n| --- | --- |\n| 1 | 2 |'), /<td>1<\/td><td>2<\/td>/);
  assert.doesNotMatch(renderMarkdown('![unsafe](file:///etc/passwd)'), /<img/);
  assert.match(renderMarkdown(`![Cat](sandbox:/images/${filename})`), new RegExp(`/api/v1/images/${filename}`));
});

test('thread controls unlock after stream and remain locked for backend busy state', () => {
  const h = harness();
  h.run('state.config={agent_config:{},orchestrator_config:{}}; state.snapshot={thread_id:"current"}; setThreadList([{thread_id:"current",title:"Hello"}]); state.busy=true; syncControls()');
  assert.equal(h.run('elements.threadList.children[0].children[0].disabled'), true);
  h.run('state.busy=false; syncControls()');
  assert.equal(h.run('elements.threadList.children[0].children[0].disabled'), false);
  h.run('state.backendBusy=true; syncControls()');
  assert.equal(h.run('elements.input.disabled'), true);
  assert.equal(h.run('elements.threadList.children[0].children[0].disabled'), true);
});

test('each resource path opens through narrow desktop bridge and browser shows useful message', async () => {
  const calls = [];
  const h = harness({ platonWindow: { openResource: async options => { calls.push(options); return { ok: true }; } } });
  h.context.field = element();
  h.context.input = { value: '/skills/\n/skills/extra/\n/skills/' };
  h.run('renderResourcePaths(field,input,"skills")');
  assert.equal(h.context.field.children[0].children.length, 2);
  const button = h.context.field.children[0].children[1].children[1];
  await button.listeners.click({ preventDefault() {} });
  assert.equal(calls[0].kind, 'skills');
  assert.equal(calls[0].path, '/skills/extra/');
  assert.equal(button.disabled, false);
  h.context.platonWindow = undefined;
  await button.listeners.click({ preventDefault() {} });
  assert.match(h.nodes.get('#toast-region').children[0].textContent, /aplikacji desktopowej/);
});
