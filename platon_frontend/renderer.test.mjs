import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('./app.js', import.meta.url), 'utf8');
function element() {
  return { children: [], listeners: {}, dataset: {}, classList: { add() {}, remove() {} }, setAttribute() {},
    focus() {}, showModal() { this.open = true; }, close() { this.open = false; this.listeners.close?.(); }, remove() { this.removed = true; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, handler) { this.listeners[name] = handler; } };
}

test('document library renders records, permits deselection at limit, and builds attachment chips', () => {
  const records = Array.from({ length: 11 }, (_, i) => ({ id: String(i), filename: `source-${i}.pdf`, collection: 'documents' }));
  const state = { documents: records, attachments: new Set(['0']), selectedForAttachment: new Set(records.slice(0, 10).map(item => item.id)) };
  const elements = { documentList: element(), attachmentStrip: element() };
  const context = vm.createContext({ state, elements, document: { createElement: element }, updateAttachmentCount() {}, removeDocument() {} });
  for (const [start, end] of [['function renderDocuments()', 'function updateAttachmentCount()'], ['function renderAttachments()', 'async function refreshThreads()']]) {
    vm.runInContext(source.slice(source.indexOf(start), source.indexOf(end)), context);
  }
  vm.runInContext('renderDocuments(); renderAttachments();', context);
  assert.equal(elements.documentList.children.length, 11);
  assert.equal(elements.documentList.children[0].children[0].disabled, false);
  assert.equal(elements.documentList.children[10].children[0].disabled, true);
  assert.equal(elements.attachmentStrip.children[0].children[0].textContent, 'source-0.pdf');
  const checkbox = elements.documentList.children[0].children[0];
  checkbox.checked = false;
  checkbox.listeners.change();
  assert.equal(state.selectedForAttachment.size, 9);
  assert.equal(elements.documentList.children[10].children[0].disabled, false);
});

test('collection filter composes with search and preserves selections in other collections', () => {
  const state = {
    documents: [
      { id: '1', filename: 'report.pdf', collection: 'finance' },
      { id: '2', filename: 'report.pdf', collection: 'ideas' },
      { id: '3', filename: 'notes.txt', collection: 'finance' },
    ],
    documentSearchQuery: 'report', documentCollection: 'finance', selectedForAttachment: new Set(['2']),
  };
  const elements = { documentList: element() };
  const context = vm.createContext({ state, elements, document: { createElement: element }, updateAttachmentCount() {} });
  vm.runInContext(source.slice(source.indexOf('function renderDocuments()'), source.indexOf('function updateAttachmentCount()')), context);
  vm.runInContext('renderDocuments()', context);
  assert.equal(elements.documentList.children.length, 1);
  elements.documentList.children[0].children[0].checked = true;
  elements.documentList.children[0].children[0].listeners.change();
  assert.deepEqual([...state.selectedForAttachment], ['2', '1']);
  state.documentCollection = 'ideas';
  vm.runInContext('renderDocuments()', context);
  assert.equal(elements.documentList.children[0].children[0].checked, true);
});

test('collection choices include existing collections and permit a new destination', () => {
  const controls = Object.fromEntries(['#document-collection', '#upload-collection', '#new-collection-field', '#collection-name'].map(id => [id, element()]));
  controls['#upload-collection'].value = 'finance';
  const state = { documents: [{ collection: 'finance' }, { collection: 'ideas' }, { collection: 'finance' }], documentCollection: 'finance' };
  const context = vm.createContext({ state, $: id => controls[id], document: { createElement: element } });
  vm.runInContext(source.slice(source.indexOf('function renderDocumentCollections()'), source.indexOf('function reconcileDocuments()')), context);
  vm.runInContext('renderDocumentCollections()', context);
  assert.deepEqual(controls['#document-collection'].children.map(item => item.value), ['', 'finance', 'ideas']);
  assert.deepEqual(controls['#upload-collection'].children.map(item => item.value), ['documents', 'finance', 'ideas', '__new__']);
  assert.equal(controls['#upload-collection'].value, 'finance');
  assert.equal(controls['#collection-name'].disabled, true);
  controls['#upload-collection'].value = '__new__';
  vm.runInContext('syncUploadCollection()', context);
  assert.equal(controls['#new-collection-field'].hidden, false);
  assert.equal(controls['#collection-name'].required, true);
  assert.equal(controls['#collection-name'].disabled, false);
});

test('RAG message contains only selected document metadata and retrieval instructions', async () => {
  const { buildRagMessage } = await import('./app.js');
  assert.equal(buildRagMessage('Explain this', []), 'Explain this');
  const message = buildRagMessage('Explain this', [{
    id: 'doc1', filename: 'math.pdf', collection: 'math', path: 'C:\\sources\\math.pdf',
    text: 'SECRET FULL PDF BODY', other: 'UNRELATED',
  }]);
  assert.match(message, /^Explain this\n\n/);
  assert.match(message, /delegate_database/);
  assert.match(message, /through RAG/);
  assert.doesNotMatch(message, /SECRET|UNRELATED|Attached documents|"text"/);
  assert.deepEqual(JSON.parse(message.split('RAG sources (metadata only):\n')[1]), [
    { filename: 'math.pdf', collection: 'math', path: 'C:\\sources\\math.pdf' },
  ]);
});

test('composer submits RAG metadata without attachment IDs and rejects stale selections', async () => {
  const { buildRagMessage } = await import('./app.js');
  const calls = [];
  const state = { attachments: new Set(['1']), documents: [{ id: '1', filename: 'math.pdf', collection: 'math' }], snapshot: {} };
  const context = vm.createContext({
    state, elements: { input: { value: 'Explain' } }, buildRagMessage, resizeInput() {}, renderAttachments() {},
    showToast: (...args) => calls.push(args), chat: (...args) => calls.push(args),
    runStreamOperation: async operation => operation(),
  });
  vm.runInContext(source.slice(source.indexOf('async function submitMessage('), source.indexOf('async function createThread()')), context);
  await vm.runInContext('submitMessage("Explain")', context);
  assert.match(calls[0][0], /"collection":"math"/);
  assert.deepEqual([...calls[0][1]], []);
  state.attachments.add('missing');
  await vm.runInContext('submitMessage("Explain")', context);
  assert.equal(calls.length, 2);
  assert.match(calls[1][0], /niedostępny/);
  assert.equal(state.attachments.has('missing'), true);
});

test('chat history displays readable RAG sources and preserves unrelated content', async () => {
  const { buildRagMessage, displayMessageContent } = await import('./app.js');
  const request = buildRagMessage('Wyjaśnij', [{ filename: 'math.pdf', collection: 'math', path: 'C:\\sources\\math.pdf' }]);
  assert.equal(displayMessageContent('user', request), 'Wyjaśnij\n\nŹródła RAG:\n• math.pdf · kolekcja math');
  assert.equal(displayMessageContent('assistant', request), request);
  assert.equal(displayMessageContent('user', 'Plain message'), 'Plain message');
  const malformed = request.replace('"filename"', '"wrong"');
  assert.equal(displayMessageContent('user', malformed), malformed);
  assert.equal(displayMessageContent('user', request + '\nKeep this'), request + '\nKeep this');
});

function modelContext(listOllamaModels) {
  const controls = Object.fromEntries(['select[name="model_name"]', 'input[name="base_url"]', '#ollama-models-hint', '#refresh-ollama-models', '#save-settings'].map(id => [id, element()]));
  controls['select[name="model_name"]'].value = 'qwen3:4b';
  controls['input[name="base_url"]'].value = 'http://localhost:11434';
  const context = vm.createContext({ state: { modelRequest: 0 }, elements: { settingsFields: {} },
    $: id => controls[id], document: { createElement: element }, listOllamaModels, friendlyError: e => e.message });
  vm.runInContext(source.slice(source.indexOf('async function refreshOllamaModels()'), source.indexOf('function renderSettings(')), context);
  return { context, controls };
}

test('Ollama dropdown retains installed selection and requires a new choice for missing models', async () => {
  let models = ['qwen3:4b', 'gemma4:e2b'];
  const { context, controls } = modelContext(async baseUrl => {
    assert.equal(baseUrl, 'http://localhost:11434');
    return models;
  });
  await vm.runInContext('refreshOllamaModels()', context);
  assert.deepEqual(controls['select[name="model_name"]'].children.map(item => item.value), ['', ...models]);
  assert.equal(controls['select[name="model_name"]'].value, 'qwen3:4b');
  assert.equal(controls['#save-settings'].disabled, false);
  models = ['other:latest'];
  await vm.runInContext('refreshOllamaModels()', context);
  assert.equal(controls['select[name="model_name"]'].value, '');
  models = [];
  await vm.runInContext('refreshOllamaModels()', context);
  assert.equal(controls['#save-settings'].disabled, true);
  assert.match(controls['#ollama-models-hint'].textContent, /Zainstaluj/);
});

test('Ollama dropdown surfaces failures and ignores stale address responses', async () => {
  const pending = [];
  const { context, controls } = modelContext(() => new Promise((resolve, reject) => pending.push({ resolve, reject })));
  const oldRequest = vm.runInContext('refreshOllamaModels()', context);
  controls['input[name="base_url"]'].value = 'http://other:11434';
  const newRequest = vm.runInContext('refreshOllamaModels()', context);
  pending[1].resolve(['new:latest']);
  await newRequest;
  pending[0].resolve(['stale:latest']);
  await oldRequest;
  assert.deepEqual(controls['select[name="model_name"]'].children.map(item => item.value), ['', 'new:latest']);
  const failed = vm.runInContext('refreshOllamaModels()', context);
  pending[2].reject(new Error('Connection refused'));
  await failed;
  assert.match(controls['#ollama-models-hint'].textContent, /Connection refused/);
  assert.equal(controls['#refresh-ollama-models'].disabled, false);
  assert.equal(controls['#save-settings'].disabled, true);
});

test('settings reads selected Ollama model into agent configuration', () => {
  const model = { name: 'model_name', value: 'gemma4:e2b', dataset: { valueType: 'string' }, closest: () => ({ dataset: { section: 'agent_config' } }) };
  const context = vm.createContext({ elements: { settingsFields: { querySelectorAll: selector => {
    assert.match(selector, /select\[name\]/);
    return [model];
  } } } });
  vm.runInContext(source.slice(source.indexOf('function readSettings()'), source.indexOf('async function showSettings()')), context);
  assert.equal(vm.runInContext('readSettings()', context).agent_config.model_name, 'gemma4:e2b');
});

test('document library filters records when search query is entered', () => {
  const records = [
    { id: '1', filename: 'report.pdf', collection: 'finance' },
    { id: '2', filename: 'notes.txt', collection: 'ideas' },
  ];
  const state = { documents: records, selectedForAttachment: new Set(), documentSearchQuery: 'finance' };
  const elements = { documentList: element() };
  const context = vm.createContext({ state, elements, document: { createElement: element }, updateAttachmentCount() {}, removeDocument() {} });
  vm.runInContext(source.slice(source.indexOf('function renderDocuments()'), source.indexOf('function updateAttachmentCount()')), context);
  vm.runInContext('renderDocuments();', context);
  assert.equal(elements.documentList.children.length, 1);
  assert.equal(elements.documentList.children[0].children[2].children[0].textContent, 'report.pdf');
});

test('image gallery opens an in-app preview and provides attachment download URL', () => {
  const body = element();
  const elements = { imageGrid: element() };
  const context = vm.createContext({
    state: { images: [{ filename: 'example.png', size_bytes: 1024, modified_at: '2026-11-01T12:00:00Z' }] },
    elements, document: { createElement: element, body },
    imageUrl: (name, download) => `/api/v1/images/${name}${download ? '?download=true' : ''}`,
    formatSize: () => '1 KB', removeImage() {},
  });
  vm.runInContext(source.slice(source.indexOf('function renderImages()'), source.indexOf('async function showImages()')), context);
  vm.runInContext('renderImages()', context);
  const card = elements.imageGrid.children[0];
  const thumbnail = card.children[0];
  assert.equal(thumbnail.target, undefined);
  thumbnail.listeners.click({ preventDefault() {} });
  const preview = body.children[0];
  assert.equal(preview.open, true);
  assert.equal(preview.children[1].src, '/api/v1/images/example.png');
  assert.equal(card.children[1].children[1].children[0].href, '/api/v1/images/example.png?download=true');
  preview.children[0].listeners.click();
  assert.equal(preview.open, false);
  assert.equal(preview.removed, true);
});

test('image gallery filters images when imageSearchQuery is present', () => {
  const elements = { imageGrid: element() };
  const context = vm.createContext({
    state: {
      images: [
        { filename: 'graph.png', size_bytes: 1024, modified_at: '2026-11-01T12:00:00Z' },
        { filename: 'photo.png', size_bytes: 2048, modified_at: '2026-11-01T12:00:00Z' },
      ],
      imageSearchQuery: 'graph',
    },
    elements, document: { createElement: element },
    imageUrl: (name) => `/api/v1/images/${name}`,
    formatSize: () => '1 KB', removeImage() {},
  });
  vm.runInContext(source.slice(source.indexOf('function renderImages()'), source.indexOf('async function showImages()')), context);
  vm.runInContext('renderImages()', context);
  assert.equal(elements.imageGrid.children.length, 1);
});

test('markdown renderer converts headers, code blocks with copy buttons, lists, bold, and escapes html', async () => {
  const { renderMarkdown } = await import('./app.js');
  const md = [
    '# Tytuł główny',
    'To jest **pogrubiony** tekst oraz `kod inline` i <script>alert(1)</script>.',
    '```python',
    'def hello():',
    '    return "world"',
    '```',
    '- punkt 1',
    '- punkt 2',
    '> Ważny cytat',
  ].join('\n');

  const html = renderMarkdown(md);
  assert.match(html, /<h1>Tytuł główny<\/h1>/);
  assert.match(html, /<strong>pogrubiony<\/strong>/);
  assert.match(html, /<code class="inline-code">kod inline<\/code>/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(html, /class="code-block" data-lang="python"/);
  assert.match(html, /class="code-copy-btn"/);
  assert.match(html, /<ul><li>punkt 1<\/li><li>punkt 2<\/li><\/ul>/);
  assert.match(html, /<blockquote><p>Ważny cytat<\/p><\/blockquote>/);
});
