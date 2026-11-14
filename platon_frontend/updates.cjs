'use strict';
const fs = require('node:fs');
const path = require('node:path');
function startUpdates({ app, dialog, updater, prepareInstall, resourcesPath = process.resourcesPath, exists = fs.existsSync }) {
  if (!app.isPackaged || !exists(path.join(resourcesPath, 'app-update.yml'))) return;
  updater ||= require('electron-updater').autoUpdater;
  updater.autoInstallOnAppQuit = false;
  updater.on('error', error => console.error('Platon update failed:', error.message));
  updater.on('update-downloaded', async () => {
    const result = await dialog.showMessageBox({ type: 'info', title: 'Platon update ready',
      message: 'An update has downloaded. Restart Platon to install it?', buttons: ['Restart and install', 'Later'], cancelId: 1 });
    if (result.response === 0) {
      try {
        await prepareInstall();
        updater.quitAndInstall();
      } catch (error) {
        dialog.showErrorBox('Update could not be installed', error.message);
      }
    }
  });
  const check = () => updater.checkForUpdatesAndNotify().catch(error => console.error('Platon update check failed:', error.message));
  void check();
  const timer = setInterval(check, 6 * 60 * 60 * 1000);
  timer.unref();
  app.once('before-quit', () => clearInterval(timer));
}
module.exports = { startUpdates };
