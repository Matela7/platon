'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');

const preferenceKeys = new Set(['platon.activeThreadId', 'platon.language', 'platon.theme', 'platon.generatedImages']);
function createPreferences(filename) {
  let queue = Promise.resolve();
  async function read() {
    try { return JSON.parse(await fs.readFile(filename, 'utf8')); }
    catch (error) { if (error.code === 'ENOENT' || error instanceof SyntaxError) return {}; throw error; }
  }
  return {
    async get(key) {
      if (!preferenceKeys.has(key)) return null;
      await queue;
      const values = await read();
      return typeof values?.[key] === 'string' ? values[key] : null;
    },
    async set(key, value) {
      if (!preferenceKeys.has(key) || typeof value !== 'string' || value.length > 1024 * 1024) return { ok: false, error: 'Invalid preference' };
      const operation = queue.then(async () => {
        const values = await read();
        const updated = Object.fromEntries(Object.entries(values || {}).filter(([name]) => preferenceKeys.has(name)));
        updated[key] = value;
        await fs.mkdir(path.dirname(filename), { recursive: true });
        await fs.writeFile(filename + '.tmp', JSON.stringify(updated), 'utf8');
        await fs.rename(filename + '.tmp', filename);
      });
      queue = operation.catch(() => {});
      try { await operation; return { ok: true }; }
      catch (error) { return { ok: false, error: error.message }; }
    },
  };
}

async function resolveResource(request, projectRoot) {
  if (!request || !['skills', 'memory'].includes(request.kind) || typeof request.path !== 'string' || !request.path.trim()) throw new Error('Invalid resource path');
  const virtualPath = request.path.trim().replaceAll('\\', '/');
  if (virtualPath.includes('\0') || virtualPath.includes(':') || virtualPath.split('/').includes('..')) throw new Error('Invalid resource path');
  const root = await fs.realpath(path.resolve(projectRoot, request.backendRoot || './.platon/agent'));
  const target = await fs.realpath(path.resolve(root, virtualPath.replace(/^\/+/, '')));
  const relative = path.relative(root, target);
  if (relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) throw new Error('Resource is outside the agent directory');
  const stat = await fs.stat(target);
  if (!stat.isDirectory() && !(stat.isFile() && /\.(md|txt)$/i.test(target))) throw new Error('Only folders and Markdown or text files can be opened');
  return target;
}

module.exports = { createPreferences, resolveResource };
