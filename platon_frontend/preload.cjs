'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('platonWindow', {
  isElectron: true,
  setupStatus: () => ipcRenderer.invoke('setup-status'),
  minimize: () => ipcRenderer.send('window-minimize'),
  toggleMaximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  isMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  openResource: (request) => ipcRenderer.invoke('resource-open', request),
  getPreference: (key) => ipcRenderer.invoke('preference-get', key),
  setPreference: (key, value) => ipcRenderer.invoke('preference-set', key, value),
});
