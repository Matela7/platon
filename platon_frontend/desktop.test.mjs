import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createPreferences, resolveResource } from './desktop.cjs';

test('desktop preferences survive restart and concurrent writes without mixing keys', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'platon-prefs-'));
  try {
    const filename = path.join(root, 'prefs.json');
    const prefs = createPreferences(filename);
    await Promise.all([prefs.set('platon.language', 'en'), prefs.set('platon.activeThreadId', 'existing-thread')]);
    const restarted = createPreferences(filename);
    assert.equal(await restarted.get('platon.language'), 'en');
    assert.equal(await restarted.get('platon.activeThreadId'), 'existing-thread');
    assert.equal((await prefs.set('arbitrary', 'x')).ok, false);
    assert.equal(await restarted.get('arbitrary'), null);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('virtual resource paths resolve under backend root and reject traversal or executables', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'platon-resource-'));
  const agentRoot = path.join(root, '.platon', 'agent');
  try {
    await mkdir(path.join(agentRoot, 'skills'), { recursive: true });
    await mkdir(path.join(agentRoot, 'memory'));
    await writeFile(path.join(agentRoot, 'memory', 'AGENTS.md'), '# Memory');
    await writeFile(path.join(agentRoot, 'skills', 'unsafe.exe'), 'not executable');
    assert.equal(await resolveResource({ kind: 'skills', path: '/skills/' }, root), path.join(agentRoot, 'skills'));
    assert.equal(await resolveResource({ kind: 'memory', path: '/memory/AGENTS.md' }, root), path.join(agentRoot, 'memory', 'AGENTS.md'));
    await assert.rejects(resolveResource({ kind: 'skills', path: '../escape' }, root), /Invalid/);
    await assert.rejects(resolveResource({ kind: 'skills', path: '/skills/unsafe.exe' }, root), /Only folders/);
    await assert.rejects(resolveResource({ kind: 'other', path: '/skills/' }, root), /Invalid/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
