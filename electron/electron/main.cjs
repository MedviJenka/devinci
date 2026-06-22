'use strict'

const { app, BrowserWindow, Menu, Tray, nativeImage, screen } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const net = require('net')

const PROJECT_ROOT = path.join(__dirname, '..', '..')   // devinci/electron/ → devinci/
const WS_PORT = 7788
let win, tray, python

function isPortInUse(port) {
  return new Promise(resolve => {
    const tester = net.createConnection({ port, host: '127.0.0.1' })
    tester.once('connect', () => { tester.destroy(); resolve(true) })
    tester.once('error',   () => resolve(false))
  })
}

// ── tray icon: programmatic blue dot ──────────────────────────────────────────

const ICON_B64 =
  'iVBORw0KGgoAAAANSUhEUgAAABYAAAAWCAYAAADEtGw7AAAAiklEQVR42mNgGEgQ0PNfDYhtoFiNGoY1' +
  'AvFxIP4BxP+h+AdUrJFkS4AasoD4PpJhuDBITRaxhjYSYSA6biTGpf/JxFn4wvQ+BQbfxxrmZAYB4SCB' +
  'xjSlBh/HFgw/qGDwD5TggCb8/1TCNnQxmDZBQbPIo3Vyo00GoVmWpmkhRNNik6YFPU2rJkoBAA/+NnZ+' +
  't/NbAAAAAElFTkSuQmCC'

function makeTrayIcon() {
  return nativeImage.createFromDataURL('data:image/png;base64,' + ICON_B64)
}

// ── Python pipeline ───────────────────────────────────────────────────────────

async function startPython() {
  if (await isPortInUse(WS_PORT)) {
    console.log('[electron] pipeline already running on', WS_PORT, '— skipping spawn')
    return
  }
  console.log('[electron] starting Python pipeline...')
  python = spawn('uv', ['run', 'python', '-m', 'desktop.pipeline_server'], {
    cwd: PROJECT_ROOT,
    stdio: 'inherit',
    shell: process.platform === 'win32',
  })
  python.on('error', e => console.error('[electron] python error:', e.message))
  python.on('close', code => console.log('[electron] python exited:', code))
}

// ── dot window ────────────────────────────────────────────────────────────────

function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize

  win = new BrowserWindow({
    width: 80,
    height: 80,
    x: width - 112,
    y: height - 112,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    movable: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (!app.isPackaged) {
    win.loadURL('http://localhost:5173')
  } else {
    win.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  // right-click on the dot → context menu
  win.webContents.on('context-menu', () => {
    Menu.buildFromTemplate([
      { label: 'Claude Listener', enabled: false },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() },
    ]).popup()
  })
}

// ── system tray ───────────────────────────────────────────────────────────────

function createTray() {
  tray = new Tray(makeTrayIcon())
  tray.setToolTip('Claude Listener')
  tray.setContextMenu(
    Menu.buildFromTemplate([{ label: 'Quit Claude Listener', click: () => app.quit() }])
  )
}

// ── lifecycle ─────────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  startPython()
  createWindow()
  createTray()
})

app.on('window-all-closed', e => e.preventDefault())   // keep alive even if window closes

app.on('before-quit', () => {
  if (python) python.kill()
})
