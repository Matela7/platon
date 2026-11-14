'use strict';

const { app, BrowserWindow, ipcMain, shell, dialog } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const { randomBytes } = require('node:crypto');
const { backendLaunch, availablePort, waitForBackend } = require('./desktop-runtime.cjs');
const { startUpdates } = require('./updates.cjs');
const { listen } = require('./server.cjs');
const { createPreferences, resolveResource } = require('./desktop.cjs');
let preferences;
function trustedSender(event) {
  return Boolean(BrowserWindow.fromWebContents(event.sender)) && event.senderFrame === event.sender.mainFrame;
}
ipcMain.handle('preference-get', async (event, key) => {
  if (!trustedSender(event)) return null;
  preferences ||= createPreferences(path.join(app.getPath('userData'), 'preferences.json'));
  return preferences.get(key);
});
ipcMain.handle('preference-set', async (event, key, value) => {
  if (!trustedSender(event)) return { ok: false };
  preferences ||= createPreferences(path.join(app.getPath('userData'), 'preferences.json'));
  return preferences.set(key, value);
});
ipcMain.handle('resource-open', async (event, request) => {
  try {
    if (!trustedSender(event)) throw new Error('Invalid window');
    const host = new URL(process.env.PLATON_BACKEND_URL || 'http://127.0.0.1:8000').hostname;
    if (!['localhost', '127.0.0.1', '[::1]'].includes(host)) throw new Error('Resources on a remote backend cannot be opened locally.');
    const target = await resolveResource(request, (app.isPackaged ? path.join(app.getPath('userData'), 'backend') : process.env.PLATON_BACKEND_DIR || path.resolve(__dirname, '..')));
    const error = await shell.openPath(target);
    return error ? { ok: false, error } : { ok: true };
  } catch (error) { return { ok: false, error: error.message }; }
});

let uiServer;
let uiServerPromise;
let backendProcess;
let windowPromise;
let shutdownPromise;
let allowQuit = false;

let setupStatus = { message: 'Starting Platon backend...', status: 'running' };
ipcMain.handle('setup-status', event => trustedSender(event) ? setupStatus : null);
let backendReady;
let backendFailure;
let backendReadyComplete = false;
let backendLog;
function maybeStartBackend() {
  if (backendReady) return backendReady;
  backendReady = (async () => {
    const dataDir = path.join(app.getPath('userData'), 'backend');
    if (app.isPackaged) fs.mkdirSync(dataDir, { recursive: true });
    const launch = backendLaunch({ packaged: app.isPackaged, resourcesPath: process.resourcesPath,
      dataDir, port: app.isPackaged ? await availablePort() : undefined });
    if (!launch) return;
    process.env.PLATON_BACKEND_URL = launch.url;
    launch.env = { ...launch.env, PLATON_SETUP_TOKEN: randomBytes(32).toString('hex') };
    if (app.isPackaged) backendLog = fs.createWriteStream(path.join(dataDir, 'backend.log'), { flags: 'a' });
    backendLog?.on('error', error => console.error('Backend log failed:', error.message));
    backendProcess = spawn(launch.executable, launch.args, {
      cwd: launch.cwd, env: launch.env, shell: false, windowsHide: true,
      stdio: backendLog ? ['ignore', 'pipe', 'pipe'] : 'ignore', detached: process.platform !== 'win32',
    });
    backendProcess.stdout?.pipe(backendLog, { end: false });
    backendProcess.stderr?.pipe(backendLog, { end: false });
    backendProcess.once('error', error => { backendFailure = error; });
    backendProcess.once('exit', (code, signal) => {
      if (!shutdownPromise && backendReadyComplete) {
        dialog.showErrorBox('Platon backend stopped', `Backend exited (${code ?? signal}). Restart Platon Desktop. Logs: ${dataDir}`);
        app.quit();
      }
    });
    await waitForBackend(launch.url, backendProcess, { timeoutMs: 300000, failure: () => backendFailure });
    if (app.isPackaged) {
      const request = async (route, method = 'GET') => {
        const response = await fetch(new URL(route, launch.url), { method, headers: { 'X-Platon-Setup-Token': launch.env.PLATON_SETUP_TOKEN }, signal: AbortSignal.timeout(15000) });
        if (!response.ok) throw new Error(`Model setup failed: HTTP ${response.status}`);
        return response.json();
      };
      await request('/setup/start', 'POST');
      while (!shutdownPromise) {
        setupStatus = await request('/setup/status');
        if (setupStatus.status === 'completed') break;
        if (setupStatus.status === 'error') throw new Error(setupStatus.error || setupStatus.message);
        if (backendFailure || backendProcess.exitCode !== null) throw backendFailure || new Error('Backend stopped during model setup.');
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    }
    backendReadyComplete = true;
  })();
  return backendReady;
}

function waitForBackendClose(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return Promise.race([
    new Promise(resolve => child.once('close', resolve)),
    new Promise(resolve => setTimeout(resolve, timeoutMs)),
  ]);
}

async function stopManagedBackend() {
  const child = backendProcess;
  if (!child || !child.pid) return;
  const isRunning = () => child.exitCode === null && child.signalCode === null;
  if (!isRunning()) return;

  if (process.platform === 'win32') {
    await new Promise(resolve => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      if (!isRunning()) return finish();
      const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
        shell: false,
        windowsHide: true,
        stdio: 'ignore',
      });
      killer.once('error', () => {
        child.kill();
        finish();
      });
      killer.once('close', finish);
    });
    await waitForBackendClose(child, 3000);
    if (isRunning()) throw new Error('Backend is still running; update installation was stopped.');
    return;
  }

  const signalGroup = signal => {
    try { process.kill(-child.pid, signal); }
    catch (error) {
      if (error.code !== 'ESRCH') console.error(`Could not send ${signal} to managed backend process group:`, error.message);
    }
  };
  signalGroup('SIGTERM');
  await waitForBackendClose(child, 1500);
  // Do not signal the saved process-group ID after uv exits; the ID could be reused.
  if (isRunning()) {
    signalGroup('SIGKILL');
    await waitForBackendClose(child, 3000);
    if (isRunning()) throw new Error('Backend is still running; update installation was stopped.');
  }
}

async function shutdown() {
  await stopManagedBackend();
  backendLog?.end();
  if (uiServer) {
    const server = uiServer;
    uiServer = undefined;
    await new Promise(resolve => {
      const timeout = setTimeout(resolve, 2000);
      timeout.unref?.();
      server.close(() => {
        clearTimeout(timeout);
        resolve();
      });
      server.closeAllConnections();
    });
  }
}

function createWindow() {
  if (windowPromise) return windowPromise;
  windowPromise = createWindowOnce().finally(() => { windowPromise = undefined; });
  return windowPromise;
}

async function createWindowOnce() {
  if (BrowserWindow.getAllWindows().length > 0) {
    BrowserWindow.getAllWindows()[0].focus();
    return;
  }
  let startupWindow;
  if (app.isPackaged) {
    startupWindow = new BrowserWindow({ width: 640, height: 360, title: 'Platon setup', autoHideMenuBar: true, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, preload: path.join(__dirname, 'preload.cjs') } });
    await startupWindow.loadFile(path.join(__dirname, 'setup.html'));
    startupWindow.on('closed', () => { if (!backendReadyComplete) app.quit(); });
  }
  await maybeStartBackend();
  if (shutdownPromise) return;
  if (!uiServerPromise) {
    uiServerPromise = listen().then(hosted => {
      uiServer = hosted.server;
      return hosted;
    }).catch(error => {
      uiServerPromise = undefined;
      throw error;
    });
  }
  const hosted = await uiServerPromise;
  const iconPath = process.platform === 'win32'
    ? path.join(__dirname, 'build', 'icon.ico')
    : path.join(__dirname, 'build', 'icon.png');
  const win = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 760,
    minHeight: 560,
    backgroundColor: '#f7f6f3',
    title: 'Platon.ai',
    icon: iconPath,
    frame: false,
    titleBarStyle: process.platform === 'darwin' ? 'hidden' : 'default',
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => {
    if (url !== hosted.url) event.preventDefault();
  });
  win.webContents.on('will-redirect', event => event.preventDefault());
  await win.loadURL(hosted.url);
  startupWindow?.close();
}

ipcMain.on('window-minimize', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  win?.minimize();
});

ipcMain.on('window-maximize', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win) return;
  if (win.isMaximized()) {
    win.unmaximize();
  } else {
    win.maximize();
  }
});

ipcMain.on('window-close', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  win?.close();
});

ipcMain.handle('window-is-maximized', (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  return win ? win.isMaximized() : false;
});

const instanceAllowed = !app.isPackaged || app.requestSingleInstanceLock();
if (!instanceAllowed) app.quit();
app.on('second-instance', () => BrowserWindow.getAllWindows()[0]?.focus());

app.whenReady().then(async () => {
  if (!instanceAllowed) return;
  await createWindow();
  startUpdates({ app, dialog, prepareInstall: async () => {
    shutdownPromise ||= shutdown();
    await shutdownPromise;
    allowQuit = true;
  } });
}).catch(error => {
  console.error('Failed to start Platon Desktop:', error);
  dialog.showErrorBox('Platon Desktop could not start', `${error.message}\nBackend log: ${path.join(app.getPath('userData'), 'backend', 'backend.log')}`);
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow().catch(console.error);
});
app.on('before-quit', event => {
  if (allowQuit) return;
  event.preventDefault();
  if (!shutdownPromise) {
    shutdownPromise = shutdown().catch(error => {
      console.error('Error while stopping Platon Desktop services:', error);
    }).finally(() => {
      allowQuit = true;
      app.quit();
    });
  }
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
