'use strict';

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
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
    const target = await resolveResource(request, process.env.PLATON_BACKEND_DIR || path.resolve(__dirname, '..'));
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

function maybeStartBackend() {
  if (backendProcess) return;
  const cwd = process.env.PLATON_BACKEND_DIR;
  if (!cwd) return;
  const executable = process.env.PLATON_UV_EXECUTABLE || 'uv';
  backendProcess = spawn(executable,
    ['run', '--locked', '--python', '3.13', 'python', '-m', 'platon.backend.app'],
    {
      cwd: path.resolve(cwd),
      shell: false,
      windowsHide: true,
      stdio: 'ignore',
      detached: process.platform !== 'win32',
    });
  backendProcess.once('error', error => console.error('Could not start configured Platon backend:', error.message));
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
  if (isRunning()) signalGroup('SIGKILL');
}

async function shutdown() {
  await stopManagedBackend();
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
  maybeStartBackend();
  if (BrowserWindow.getAllWindows().length > 0) {
    BrowserWindow.getAllWindows()[0].focus();
    return;
  }
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

app.whenReady().then(createWindow).catch(error => {
  console.error('Failed to start Platon Desktop:', error);
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
