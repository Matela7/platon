'use strict';

const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const { pipeline } = require('node:stream');

const ROOT = __dirname;
const FILES = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/index.html', ['index.html', 'text/html; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/api.js', ['api.js', 'text/javascript; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/i18n.js', ['i18n.js', 'text/javascript; charset=utf-8']],
  ...['idle', 'running', 'waving', 'waiting', 'review', 'running-left', 'running-right', 'jumping'].map(state => [`/pixel-corgi/qa/final-previews/${state}.gif`, [`pixel-corgi/qa/final-previews/${state}.gif`, 'image/gif']]),
  ['/pixel-corgi/qa/final-frames/idle/00.png', ['pixel-corgi/qa/final-frames/idle/00.png', 'image/png']],
  ['/pixel-corgi/qa/final-frames/running-left/00.png', ['pixel-corgi/qa/final-frames/running-left/00.png', 'image/png']],
  ['/icon.png', ['build/icon.png', 'image/png']],
  ['/favicon.ico', ['build/icon.ico', 'image/x-icon']],
]);
const API_PREFIX = '/api/v1/';
function backendURL() {
const backend = new URL(process.env.PLATON_BACKEND_URL || 'http://127.0.0.1:8000');
if (!['http:', 'https:'].includes(backend.protocol) || backend.username || backend.password) {
  throw new Error('PLATON_BACKEND_URL must be an HTTP(S) URL without credentials');
}

return backend;
}

function createServer() {
  // Native <img> requests bypass the renderer's API queue. Serialize all
  // backend traffic here as well, through the end of each response body.
  let backendRequests = Promise.resolve();
  return http.createServer((req, res) => {
    let url;
    try { url = new URL(req.url, 'http://127.0.0.1'); }
    catch { res.writeHead(400).end('Bad request'); return; }
    if (url.pathname === '/ollama/models') {
      listOllamaModels(req, res, url);
      return;
    }
    if (url.pathname.startsWith(API_PREFIX)) {
      if (url.pathname === '/api/v1/agent-runtime/stop') {
        proxy(req, res, url);
      } else {
        backendRequests = backendRequests.then(() => new Promise(resolve => {
          if (res.destroyed || req.aborted) return resolve();
          res.once('close', resolve);
          proxy(req, res, url);
        })).catch(error => {
          if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ detail: `Backend proxy failed: ${error.message}` }));
        });
      }
      return;
    }
    const entry = FILES.get(url.pathname);
    if (!entry || req.method !== 'GET' && req.method !== 'HEAD') {
      res.writeHead(404, { 'Cache-Control': 'no-store' }).end('Not found');
      return;
    }
    const [file, type] = entry;
    const filePath = path.join(ROOT, file);
    res.writeHead(200, {
      'Content-Type': type,
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': 'no-store',
      'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
      'Referrer-Policy': 'no-referrer',
    });
    if (req.method === 'HEAD') return res.end();
    const stream = fs.createReadStream(filePath);
    stream.on('error', () => { if (!res.headersSent) res.writeHead(500); res.end('Unable to read UI file'); });
    stream.pipe(res);
  });
}

function listOllamaModels(req, res, url) {
  const reply = (status, body) => {
    if (res.writableEnded) return;
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify(body));
  };
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    reply(405, { detail: 'Method not allowed' });
    return;
  }
  // Only the local UI may select an Ollama host; never forward caller headers or redirects.
  if ((req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) || req.headers['sec-fetch-site'] === 'cross-site') {
    reply(403, { detail: 'Forbidden origin' });
    return;
  }
  let target;
  try {
    const base = new URL(url.searchParams.get('base_url') || 'http://localhost:11434');
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) throw new Error();
    target = new URL(`${base.pathname.replace(/\/$/, '')}/api/tags`, base.origin);
  } catch {
    reply(400, { detail: 'Adres Ollama musi być adresem HTTP(S) bez danych logowania, parametrów i fragmentu.' });
    return;
  }
  const transport = target.protocol === 'https:' ? https : http;
  const outgoing = transport.get(target, { headers: { Accept: 'application/json' } }, upstream => {
    const chunks = [];
    let size = 0;
    upstream.on('data', chunk => {
      size += chunk.length;
      if (size > 1024 * 1024) {
        reply(502, { detail: 'Lista modeli Ollama jest zbyt duża.' });
        upstream.destroy();
        outgoing.destroy();
        return;
      }
      chunks.push(chunk);
    });
    upstream.on('error', error => reply(502, { detail: `Nie udało się odczytać listy modeli Ollama: ${error.message}` }));
    upstream.on('end', () => {
      if (res.writableEnded) return;
      if (upstream.statusCode !== 200) {
        reply(502, { detail: `Ollama zwróciła HTTP ${upstream.statusCode} podczas pobierania modeli.` });
        return;
      }
      try {
        const payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if (!Array.isArray(payload.models)) throw new Error();
        reply(200, { models: payload.models.map(model => ({ name: model?.name })) });
      } catch {
        reply(502, { detail: 'Ollama zwróciła nieprawidłową listę modeli.' });
      }
    });
  });
  const timeout = setTimeout(() => outgoing.destroy(new Error('Przekroczono czas oczekiwania na Ollama.')), 10000);
  outgoing.once('close', () => clearTimeout(timeout));
  outgoing.on('error', error => reply(502, { detail: `Nie udało się pobrać modeli Ollama: ${error.message}` }));
  res.on('close', () => outgoing.destroy());
}

function proxy(req, res, url) {
  if (!['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'].includes(req.method)) {
    res.writeHead(405, { Allow: 'GET, POST, PUT, DELETE, OPTIONS' }).end();
    return;
  }
  const backend = backendURL();
  const target = new URL(url.pathname + url.search, backend);
  const headers = { ...req.headers, host: backend.host, connection: 'close' };
  delete headers['content-length'];
  const transport = target.protocol === 'https:' ? https : http;
  const outgoing = transport.request(target, { method: req.method, headers }, upstream => {
    const responseHeaders = { ...upstream.headers };
    if (url.pathname.startsWith('/api/v1/images')) responseHeaders['cache-control'] = 'no-store';
    delete responseHeaders['access-control-allow-origin'];
    res.writeHead(upstream.statusCode || 502, responseHeaders);
    pipeline(upstream, res, () => {});
  });
  outgoing.on('error', error => {
    if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ detail: `Backend proxy failed: ${error.message}` }));
  });
  req.on('aborted', () => outgoing.destroy());
  pipeline(req, outgoing, error => { if (error) outgoing.destroy(error); });
}

function listen() {
  const server = createServer();
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject);
      resolve({ server, url: `http://127.0.0.1:${server.address().port}/` });
    });
  });
}

module.exports = { listen };
