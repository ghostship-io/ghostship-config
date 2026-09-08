import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import Module, { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { installElectronProxy } = require('../bridge/electron-proxy.cjs');

test('bridged windows remain discoverable by Electron for native state broadcasts', () => {
  const windows = [];
  class BrowserWindow extends EventEmitter {
    constructor() {
      super();
      this.id = windows.length + 1;
      this.webContents = new EventEmitter();
      this.webContents.send = (...args) => this.webContents.emit('message', ...args);
      windows.push(this);
    }
    isDestroyed() { return false; }
    // Electron 42 uses constructor.name, not instanceof, in these lookups:
    // https://github.com/electron/electron/blob/v42.3.0/lib/browser/api/browser-window.ts
    static getAllWindows() {
      return windows.filter((window) => window.constructor.name === 'BrowserWindow');
    }
    static fromId(id) {
      return this.getAllWindows().find((window) => window.id === id) || null;
    }
  }
  const electron = {
    BrowserWindow, app: new EventEmitter(), ipcMain: new EventEmitter(),
    shell: {}, Menu: {}, dialog: {},
  };
  const originalLoad = Module._load;
  try {
    installElectronProxy(electron, {
      setBrowserFullscreenStateHandler() {}, setBrowserGuestFactory() {},
      setBrowserFocusStateHandler() {}, isBrowserFocused: () => false,
      registerAuxiliaryWindow() {},
    });
    const proxy = Module._load('electron', { filename: '/upstream/main.cjs' });
    const primary = new proxy.BrowserWindow({ webPreferences: { preload: '/upstream/preload.js' } });
    const auxiliary = new proxy.BrowserWindow();
    assert.deepEqual(proxy.BrowserWindow.getAllWindows(), [primary, auxiliary]);
    assert.equal(proxy.BrowserWindow.fromId(primary.id), primary);
    const received = [];
    primary.webContents.on('message', (...args) => received.push(args));
    const update = { type: 'global-state-updated', keys: ['local-projects'] };
    for (const window of proxy.BrowserWindow.getAllWindows()) {
      window.webContents.send('codex_desktop:message-for-view', update);
    }
    assert.deepEqual(received, [['codex_desktop:message-for-view', update]]);
  } finally {
    Module._load = originalLoad;
  }
});
