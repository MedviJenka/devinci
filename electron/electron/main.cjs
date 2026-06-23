'use strict'

const { app, BrowserWindow, Menu, Tray, nativeImage, screen, ipcMain } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const net = require('net')

const PROJECT_ROOT = path.join(__dirname, '..', '..')   // devinci/electron/ → devinci/
const WS_PORT = 7788
let win, tray, python

function isPortInUse(port) {
  return new Promise(resolve => {
    const tester = net.createConnection({ port, host: '127.0.0.1' })
    tester.setTimeout(500)
    tester.once('connect', () => { tester.destroy(); resolve(true)  })
    tester.once('error',   () => { tester.destroy(); resolve(false) })
    tester.once('timeout', () => { tester.destroy(); resolve(false) })
  })
}

function killPortHolder(port) {
  if (process.platform !== 'win32') return
  const { execSync } = require('child_process')
  try {
    const out = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' })
    for (const line of out.split('\n').filter(l => l.includes('LISTENING'))) {
      const pid = line.trim().split(/\s+/).pop()
      if (pid && /^\d+$/.test(pid) && pid !== '0') {
        execSync(`taskkill /F /PID ${pid}`, { stdio: 'ignore' })
        console.log(`[electron] killed stale process on :${port} (PID ${pid})`)
      }
    }
  } catch {}
}

// ── tray icon: programmatic blue dot ──────────────────────────────────────────

const ICON_B64 =
  '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'

function makeTrayIcon() {
  return nativeImage.createFromDataURL('data:image/png;base64,' + ICON_B64)
}

// ── Python pipeline ───────────────────────────────────────────────────────────

async function startPython() {
  if (await isPortInUse(WS_PORT)) {
    console.log('[electron] stale process on', WS_PORT, '— killing it')
    killPortHolder(WS_PORT)
    await new Promise(r => setTimeout(r, 700))
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

// ── dashboard IPC ─────────────────────────────────────────────────────────────

const DOT_W = 80, DOT_H = 80, DASH_W = 400, DASH_H = 520

ipcMain.on('toggle-dashboard', (_event, open) => {
  if (!win) return
  const { width, height } = screen.getPrimaryDisplay().workAreaSize
  // keep the bottom-right corner of the window anchored
  const anchorRight  = width  - 32
  const anchorBottom = height - 32
  if (open) {
    win.setBounds({ x: anchorRight - DASH_W, y: anchorBottom - DASH_H, width: DASH_W, height: DASH_H })
  } else {
    win.setBounds({ x: anchorRight - DOT_W, y: anchorBottom - DOT_H, width: DOT_W, height: DOT_H })
  }
})

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
