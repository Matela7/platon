import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('./api.js', import.meta.url), 'utf8');
const api = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const collect = async (events) => { const result = []; for await (const event of events) result.push(event); return result; };
test('chat waits until image listing has released the shared backend lock', async () => {
  let finishListing;
  const listingDone = new Promise(resolve => { finishListing = resolve; });
  let listing = false;
  let chatStarted = false;
  globalThis.fetch = async url => {
    if (url.endsWith('/images')) {
      listing = true;
      return { ok: true, json: async () => { await listingDone; listing = false; return { data: [] }; } };
    }
    assert.equal(listing, false);
    chatStarted = true;
    return new Response('{"type":"result","data":{}}\n');
  };
  const images = api.listImages();
  const conversation = collect(api.chat('hello'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(listing, true);
  assert.equal(chatStarted, false);
  finishListing();
  await Promise.all([images, conversation]);
  assert.equal(chatStarted, true);
});

test('read requests wait for the stream but Stop bypasses it and cleanup unlocks the queue', async () => {
  const calls = [];
  globalThis.fetch = async url => {
    calls.push(url);
    if (url.endsWith('/chat')) return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new TextEncoder().encode('{"type":"delta","data":"working"}\n'));
    } }));
    return Response.json({ data: {} });
  };
  const stream = api.chat('hello');
  await stream.next();
  const snapshot = api.getSnapshot();
  await api.stop();
  assert.equal(calls.some(url => url.endsWith('/snapshot')), false);
  assert.equal(calls.some(url => url.endsWith('/stop')), true);
  await stream.return();
  await snapshot;
  assert.equal(calls.some(url => url.endsWith('/snapshot')), true);
});

test('only pre-start busy rejection is retried, never an accepted stream failure', async () => {
  let calls = 0;
  globalThis.fetch = async () => ++calls === 1
    ? Response.json({ detail: 'Agent runtime is busy.' }, { status: 409 })
    : new Response('{"type":"result","data":{}}\n');
  await collect(api.chat('hello'));
  assert.equal(calls, 2);
  calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response('{"type":"delta","data":"partial"}\n');
  };
  await assert.rejects(collect(api.chat('hello')), /przerwane/);
  assert.equal(calls, 1);
});
test('NDJSON preserves UTF-8 across byte boundaries and accepts final line without newline', async () => {
  const bytes = new TextEncoder().encode('{"type":"delta","data":"żółć"}\n{"type":"result","data":{}}');
  globalThis.fetch = async () => new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  }}));
  assert.equal((await collect(api.chat('test')))[0].data, 'żółć');
});
test('truncated stream is not reported as successful', async () => {
  globalThis.fetch = async () => new Response('{"type":"delta","data":"partial"}\n');
  await assert.rejects(collect(api.chat('test')), /przerwane/);
});
test('HTTP error retains backend operation context', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({detail:'Runtime busy'}), {status:409});
  await assert.rejects(api.getSnapshot(), error => error.status === 409 && error.message === 'Runtime busy');
});

test('chat sends document_ids in the backend request payload', async () => {
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response('{"type":"result","data":{}}\n', {
      headers: { 'Content-Type': 'application/x-ndjson' },
    });
  };
  await collect(api.chat('Summarize these files', ['doc-1', 'doc-2']));
  assert.equal(request.url, '/api/v1/agent-runtime/chat');
  assert.deepEqual(JSON.parse(request.options.body), {
    message: 'Summarize these files',
    document_ids: ['doc-1', 'doc-2'],
  });
});

test('thread IDs are escaped as a single path segment', async () => {
  let requestedUrl;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return Response.json({ status: 'success', data: { deleted: true } });
  };
  await api.deleteThread('team/a b?c#d');
  assert.equal(requestedUrl, '/api/v1/agent-runtime/threads/team%2Fa%20b%3Fc%23d');
});

test('RAG source selection sends metadata without triggering backend attachment extraction', async () => {
  const { buildRagMessage } = await import('./app.js');
  let body;
  globalThis.fetch = async (_url, options) => {
    body = JSON.parse(options.body);
    return new Response('{"type":"result","data":{}}\n');
  };
  await collect(api.chat(buildRagMessage('Explain this PDF', [{
    id: 'doc-1', filename: 'math.pdf', collection: 'math', text: 'FULL DOCUMENT BODY',
  }]), []));
  assert.deepEqual(body.document_ids, []);
  assert.match(body.message, /delegate_database/);
  assert.match(body.message, /"filename":"math.pdf","collection":"math"/);
  assert.doesNotMatch(body.message, /FULL DOCUMENT BODY|Attached documents/);
});

test('stream-level error event is yielded as a terminal event', async () => {
  globalThis.fetch = async () => new Response(
    '{"type":"error","data":{"message":"Execution failed"}}\n',
    { headers: { 'Content-Type': 'application/x-ndjson' } },
  );
  assert.deepEqual(await collect(api.chat('test')), [
    { type: 'error', data: { message: 'Execution failed' } },
  ]);
});

test('aborting a stream rejects iteration with AbortError', async () => {
  const controller = new AbortController();
  let requestSignal;
  globalThis.fetch = async (_url, options) => {
    requestSignal = options.signal;
    options.signal.addEventListener('abort', () => streamController.error(
      new DOMException('The operation was aborted.', 'AbortError'),
    ), { once: true });
    return new Response(new ReadableStream({
      start(stream) {
        streamController = stream;
        stream.enqueue(new TextEncoder().encode('{"type":"delta","data":"working"}\n'));
      },
    }));
  };
  let streamController;
  const iterator = api.chat('test', [], { signal: controller.signal });
  assert.equal((await iterator.next()).value.type, 'delta');
  controller.abort();
  await assert.rejects(iterator.next(), { name: 'AbortError' });
  assert.equal(requestSignal.aborted, true);
});

test('stopping iteration cancels the underlying response reader', async () => {
  let readerCancelled = false;
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"type":"delta","data":"working"}\n'));
    },
    cancel() { readerCancelled = true; },
  }));
  const iterator = api.chat('test');
  assert.equal((await iterator.next()).value.type, 'delta');
  await iterator.return();
  assert.equal(readerCancelled, true);
});

test('Ollama model list uses configured host and returns unique installed names', async () => {
  let requestedUrl;
  globalThis.fetch = async url => {
    requestedUrl = url;
    return Response.json({ models: [{ name: 'qwen3:4b' }, { name: 'gemma4:e2b' }, { name: 'qwen3:4b' }, {}] });
  };
  assert.deepEqual(await api.listOllamaModels('http://192.168.1.10:11434/ollama'), ['gemma4:e2b', 'qwen3:4b']);
  const url = new URL(requestedUrl, 'http://localhost');
  assert.equal(url.pathname, '/ollama/models');
  assert.equal(url.searchParams.get('base_url'), 'http://192.168.1.10:11434/ollama');
});

test('Ollama model errors remain visible and an empty installation stays empty', async () => {
  globalThis.fetch = async () => Response.json({ models: [] });
  assert.deepEqual(await api.listOllamaModels(), []);
  globalThis.fetch = async () => Response.json({ detail: 'Connection refused' }, { status: 502 });
  await assert.rejects(api.listOllamaModels(), error => error.status === 502 && error.message === 'Connection refused');
  globalThis.fetch = async () => Response.json({ invalid: [] });
  await assert.rejects(api.listOllamaModels(), /nieprawidłową listę/);
});
