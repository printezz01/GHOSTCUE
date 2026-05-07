/**
 * interfaces/overlay/main.js — Electron wrapper for GhostCue overlay
 * 
 * Phase 4 (stretch): Wraps the overlay HTML in a frameless, transparent,
 * always-on-top Electron window for true Cluely-style behavior.
 * 
 * Launch: npm run overlay  (requires electron in optionalDependencies)
 * Fallback: just open index.html in any Chromium browser — fully functional.
 */

const { app, BrowserWindow, globalShortcut } = require('electron');
const path = require('path');

let win = null;

function createWindow() {
  win = new BrowserWindow({
    width: 380,
    height: 620,
    frame: false,           // Frameless — overlay has its own drag handle
    transparent: true,      // See-through background for glassmorphism
    alwaysOnTop: true,      // Stays above all windows (Cluely-style)
    skipTaskbar: true,      // Hidden from taskbar — stealth mode
    resizable: true,
    minimizable: false,
    maximizable: false,
    hasShadow: false,       // We render our own shadow in CSS
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  // Load the self-contained overlay HTML
  win.loadFile(path.join(__dirname, 'index.html'));

  // Position in top-right corner of screen
  const { screen } = require('electron');
  const display = screen.getPrimaryDisplay();
  const { width } = display.workAreaSize;
  win.setPosition(width - 400, 60);

  win.on('closed', () => { win = null; });
}

app.whenReady().then(() => {
  createWindow();

  // Toggle visibility with Ctrl+Shift+G
  globalShortcut.register('CommandOrControl+Shift+G', () => {
    if (win) {
      win.isVisible() ? win.hide() : win.show();
    }
  });
});

app.on('window-all-closed', () => {
  globalShortcut.unregisterAll();
  app.quit();
});
