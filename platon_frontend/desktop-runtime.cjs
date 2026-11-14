'use strict';
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');

function backendLaunch({ packaged, resourcesPath, dataDir, env = process.env, platform = process.platform, port }) {
  if (packaged) return {
    executable: path.join(resourcesPath, 'backend', `platon-backend${platform === 'win32' ? '.exe' : ''}`),
    args: [], cwd: dataDir,
    env: { ...env, PYTHONIOENCODING: 'utf-8', PLATON_DATA_DIR: dataDir, PLATON_BACKEND_HOST: '127.0.0.1', PLATON_BACKEND_PORT: String(port),
      PLATON_PYTHON_EXECUTABLE: path.join(resourcesPath, 'python', ...(platform === 'win32' ? ['python.exe'] : ['bin', 'python3.13'])) },
    url: `http://127.0.0.1:${port}`,
  };
  if (!env.PLATON_BACKEND_DIR) return null;
  return { executable: env.PLATON_UV_EXECUTABLE || 'uv',
    args: ['run', '--locked', '--python', '3.13', 'python', '-m', 'platon.backend.app'],
    cwd: path.resolve(env.PLATON_BACKEND_DIR), env,
    url: env.PLATON_BACKEND_URL || 'http://127.0.0.1:8000' };
}
function availablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}
function probe(url) {
  return new Promise(resolve => {
    const request = http.get(new URL('/health', url), response => {
      let body = '';
      response.on('data', chunk => { body += chunk; if (body.length > 65536) request.destroy(); });
      response.on('end', () => {
        try { resolve(response.statusCode === 200 && JSON.parse(body).status === 'ok'); }
        catch { resolve(false); }
      });
      response.on('error', () => resolve(false));
    });
    request.setTimeout(1000, () => request.destroy());
    request.on('error', () => resolve(false));
  });
}
async function waitForBackend(url, child, { timeoutMs = 120000, intervalMs = 250, failure = () => null } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const error = failure();
    if (error) throw error;
    if (child && (child.exitCode !== null || child.signalCode !== null)) {
      throw new Error(`Backend stopped before becoming ready (exit ${child.exitCode}, signal ${child.signalCode}).`);
    }
    if (await probe(url)) return;
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error(`Backend did not become ready within ${timeoutMs / 1000} seconds.`);
}
module.exports = { backendLaunch, availablePort, waitForBackend };
