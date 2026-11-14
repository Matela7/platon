import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { backendLaunch, waitForBackend, availablePort } = require('./desktop-runtime.cjs');
const { startUpdates } = require('./updates.cjs');
test('packaged backend uses bundled executables and writable data without uv', () => {
  for (const platform of ['win32', 'darwin', 'linux']) {
    const launch = backendLaunch({ packaged: true, resourcesPath: '/resources', dataDir: '/user/data', env: {}, platform, port: 12345 });
    assert.match(launch.executable, /backend[\\/]platon-backend/);
    assert.equal(launch.cwd, '/user/data');
    assert.equal(launch.env.PLATON_DATA_DIR, '/user/data');
    assert.equal(launch.env.PLATON_BACKEND_PORT, '12345');
    assert.match(launch.env.PLATON_PYTHON_EXECUTABLE, platform === 'win32' ? /python.exe$/ : /python3.13$/);
    assert.deepEqual(launch.args, []);
  }
});
test('development only starts an explicitly configured checkout', () => {
  assert.equal(backendLaunch({ packaged: false, env: {} }), null);
  assert.equal(backendLaunch({ packaged: false, env: { PLATON_BACKEND_DIR: '.' } }).executable, 'uv');
});
test('readiness requires the health body and detects startup failure', async () => {
  let ready = false;
  const server = http.createServer((req, res) => res.end(JSON.stringify({ status: ready ? 'ok' : 'starting' })));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    await assert.rejects(waitForBackend(url, null, { timeoutMs: 25, intervalMs: 5 }), /did not become ready/);
    ready = true;
    await waitForBackend(url, null, { timeoutMs: 100 });
    await assert.rejects(waitForBackend(url, { exitCode: 1, signalCode: null }), /stopped before/);
    await assert.rejects(waitForBackend(url, null, { failure: () => new Error('spawn failed') }), /spawn failed/);
  } finally { await new Promise(resolve => server.close(resolve)); }
  assert.ok(await availablePort() > 0);
});
test('updates install only after managed backend shutdown', async () => {
  const handlers = {}; const order = [];
  const updater = { on: (name, callback) => { handlers[name] = callback; }, checkForUpdatesAndNotify: async () => {}, quitAndInstall: () => order.push('install') };
  startUpdates({ app: { isPackaged: true, once: () => {} }, dialog: { showMessageBox: async () => ({ response: 0 }) }, updater,
    exists: () => true, resourcesPath: '/resources', prepareInstall: async () => { await Promise.resolve(); order.push('shutdown'); } });
  assert.equal(updater.autoInstallOnAppQuit, false);
  await handlers['update-downloaded']();
  assert.deepEqual(order, ['shutdown', 'install']);
});

test('failed backend shutdown prevents update installation', async () => {
  const handlers = {}; let installed = false; let errorShown = false;
  const updater = { on: (name, callback) => { handlers[name] = callback; }, checkForUpdatesAndNotify: async () => {}, quitAndInstall: () => { installed = true; } };
  startUpdates({ app: { isPackaged: true, once: () => {} }, dialog: { showMessageBox: async () => ({ response: 0 }), showErrorBox: () => { errorShown = true; } }, updater,
    exists: () => true, resourcesPath: '/resources', prepareInstall: async () => { throw new Error('still running'); } });
  await handlers['update-downloaded']();
  assert.equal(installed, false);
  assert.equal(errorShown, true);
});
