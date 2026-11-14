import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
let backendRequest;
let ollamaRequest;
let imageInFlight = false;
let releaseHeldImage;
let imageCalls = [];
const ollamaServer = http.createServer((req, res) => {
  ollamaRequest = { method: req.method, url: req.url, authorization: req.headers.authorization };
  if (req.url === '/broken/api/tags') {
    res.writeHead(200).end('not JSON');
  } else if (req.url === '/redirect/api/tags') {
    res.writeHead(302, { Location: '/api/tags' }).end();
  } else {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ models: [{ name: 'qwen3:4b', size: 100 }] }));
  }
});
const backendServer = http.createServer((req, res) => {
  const chunks = [];
  req.on('data', chunk => chunks.push(chunk));
  req.on('end', () => {
    backendRequest = { method: req.method, url: req.url, body: Buffer.concat(chunks).toString() };
    if (req.url.startsWith('/api/v1/images/')) {
      imageCalls.push(req.url);
      if (imageInFlight) return res.writeHead(409).end('Agent runtime is busy.');
      imageInFlight = true;
      res.writeHead(200, { 'Content-Type': 'image/png' });
      res.write('PNG start');
      const finish = () => { imageInFlight = false; res.end(' PNG end'); };
      if (req.url.endsWith('/held.png')) releaseHeldImage = finish;
      else setTimeout(finish, 15);
      return;
    }
    res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
    res.write('{"type":"delta"}\n');
    setTimeout(() => res.end('{"type":"result"}\n'), 10);
  });
});

backendServer.listen(0, '127.0.0.1');
await new Promise(resolve => backendServer.once('listening', resolve));
ollamaServer.listen(0, '127.0.0.1');
await new Promise(resolve => ollamaServer.once('listening', resolve));
const ollamaUrl = `http://127.0.0.1:${ollamaServer.address().port}`;
process.env.PLATON_BACKEND_URL = `http://127.0.0.1:${backendServer.address().port}`;
const { listen } = require('./server.cjs');
const { server: uiServer, url: uiUrl } = await listen();

after(async () => {
  await Promise.all([
    new Promise(resolve => uiServer.close(resolve)),
    new Promise(resolve => backendServer.close(resolve)),
    new Promise(resolve => ollamaServer.close(resolve)),
  ]);
});

test('API proxy forwards request and preserves streamed NDJSON response', async () => {
  const response = await fetch(new URL('/api/v1/agent-runtime/chat?stream=1', uiUrl), {
    method: 'POST',
    headers: { 'content-type': 'application/json', accept: 'application/x-ndjson' },
    body: '{"message":"hello"}',
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'application/x-ndjson');
  assert.equal(await response.text(), '{"type":"delta"}\n{"type":"result"}\n');
  assert.deepEqual(backendRequest, {
    method: 'POST',
    url: '/api/v1/agent-runtime/chat?stream=1',
    body: '{"message":"hello"}',
  });
});

test('unknown UI paths are not served from the filesystem', async () => {
  const response = await fetch(new URL('/package.json', uiUrl));
  assert.equal(response.status, 404);
});

test('simultaneous native image requests complete without conflicting backend downloads', async () => {
  const responses = await Promise.all(['old-a', 'old-b', 'old-c', 'new'].map(async name => {
    const response = await fetch(new URL(`/api/v1/images/${name}.png`, uiUrl));
    return { status: response.status, content: await response.text() };
  }));
  for (const response of responses) {
    assert.equal(response.status, 200);
    assert.equal(response.content, 'PNG start PNG end');
  }
});

test('proxy queues through the complete image body while Stop bypasses the queue', async () => {
  const held = await fetch(new URL('/api/v1/images/held.png', uiUrl));
  const next = fetch(new URL('/api/v1/images/queued.png', uiUrl));
  try {
    const stop = await fetch(new URL('/api/v1/agent-runtime/stop', uiUrl), { method: 'POST' });
    assert.equal(stop.status, 200);
    await stop.text();
    assert.equal(imageCalls.includes('/api/v1/images/queued.png'), false);
  } finally { releaseHeldImage(); }
  assert.equal(await held.text(), 'PNG start PNG end');
  const response = await next;
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'PNG start PNG end');
});

test('corgi animation and reduced-motion assets are served but source files stay private', async () => {
  for (const [asset, type] of [
    ...['idle', 'waving', 'running', 'waiting', 'review', 'running-left', 'running-right', 'jumping'].map(state => [`/pixel-corgi/qa/final-previews/${state}.gif`, 'image/gif']),
    ['/pixel-corgi/qa/final-frames/idle/00.png', 'image/png'],
    ['/pixel-corgi/qa/final-frames/running-left/00.png', 'image/png'],
  ]) {
    const response = await fetch(new URL(asset, uiUrl));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('content-type'), type);
    assert.ok((await response.arrayBuffer()).byteLength > 0);
  }
  assert.equal((await fetch(new URL('/pixel-corgi/pet_request.json', uiUrl))).status, 404);
  assert.equal((await fetch(new URL('/desktop.cjs', uiUrl))).status, 404);
});

test('frontend model route queries configured Ollama tags without forwarding credentials', async () => {
  const query = new URLSearchParams({ base_url: `${ollamaUrl}/ollama/` });
  const response = await fetch(new URL(`/ollama/models?${query}`, uiUrl), { headers: { authorization: 'test-secret' } });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { models: [{ name: 'qwen3:4b' }] });
  assert.deepEqual(ollamaRequest, { method: 'GET', url: '/ollama/api/tags', authorization: undefined });
});

test('frontend model route rejects invalid targets, methods, and foreign origins', async () => {
  for (const base_url of ['file:///etc/passwd', 'http://user:password@localhost:11434', 'http://localhost:11434?query=1']) {
    const response = await fetch(new URL(`/ollama/models?${new URLSearchParams({ base_url })}`, uiUrl));
    assert.equal(response.status, 400);
  }
  assert.equal((await fetch(new URL('/ollama/models', uiUrl), { method: 'POST' })).status, 405);
  assert.equal((await fetch(new URL('/ollama/models', uiUrl), { headers: { Origin: 'https://other.example' } })).status, 403);
});

test('frontend model route reports invalid responses and does not follow redirects', async () => {
  for (const path of ['broken', 'redirect']) {
    const query = new URLSearchParams({ base_url: `${ollamaUrl}/${path}` });
    const response = await fetch(new URL(`/ollama/models?${query}`, uiUrl));
    assert.equal(response.status, 502);
    assert.match((await response.json()).detail, /Ollama/);
  }
});
