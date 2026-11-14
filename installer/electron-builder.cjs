'use strict';
const path = require('node:path');
const app = require('../platon_frontend/package.json');
const config = { ...app.build,
  win: { ...app.build.win, target: ['nsis'] },
  directories: { app: path.join(__dirname, 'staging/app'), output: path.join(__dirname, 'dist'), buildResources: path.join(__dirname, 'staging/app/build') },
  extraResources: [
    process.platform === 'linux'
      ? { from: path.join(__dirname, 'staging/backend/platon-backend'), to: 'backend', filter: ['**/*'] }
      : { from: path.join(__dirname, 'staging/backend'), to: 'backend', filter: ['platon-backend', 'platon-backend.exe'] },
    { from: path.join(__dirname, 'staging/python'), to: 'python' },
  ],
  publish: null,
};
{
  const url = new URL(process.env.PLATON_UPDATE_URL || 'https://github.com/Matela7/platon/releases/latest/download');
  if (url.protocol !== 'https:' || url.username || url.password) throw new Error('PLATON_UPDATE_URL must be an HTTPS URL without credentials');
  config.publish = [{ provider: 'generic', url: url.href }];
}
module.exports = config;
