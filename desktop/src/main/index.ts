/**
 * Electron main: the floating overlay (pill), the workspace window, the global hotkey, OS sensing,
 * and the local backend process. Secrets other than the AG Studio key never reach a renderer.
 */
import { app, BrowserWindow, clipboard, globalShortcut, ipcMain, nativeImage, screen, shell } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'
import type { Config, Context, Settings } from '../shared/types'
import { createSense } from './sense'
import { createDesktop } from './desktop'
import { createSpeaker, createVoice } from './voice'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const ROOT = resolve(app.getAppPath(), '../..') // repo root in dev: app/desktop -> ../..
const HOTKEY = 'CommandOrControl+Shift+Space'
const SIZE = { width: 460, height: 660 }
const ICON = join(app.getAppPath(), 'build/icon.png')

const env: Record<string, string> = { ...readEnv(join(ROOT, '.env')), ...(process.env as Record<string, string>) }
const config: Config = {
  backendUrl: env.BIZOS_BACKEND_URL || 'http://127.0.0.1:8787',
  token: env.BIZOS_BACKEND_URL ? env.BIZOS_TOKEN || '' : randomBytes(24).toString('hex'),
  agLicense: env.AG_STUDIO_LICENSE_KEY || '',
  platform: process.platform,
}
const sense = createSense(process.platform)
const voice = createVoice(process.platform)
const speaker = createSpeaker(process.platform)
const desktop = createDesktop(() => sense.read('')) // empty clipboard: never hand it to an agent action
const settingsFile = () => join(app.getPath('userData'), 'settings.json')
// Global settings (apply to every app and site): per-app off switch and screen-capture "Always yes".
let settings: Settings = { muted: [], alwaysCapture: false }
const saveSettings = () => writeFileSync(settingsFile(), JSON.stringify(settings, null, 2))
let overlay: BrowserWindow | null = null
let workspace: BrowserWindow | null = null
let backend: ChildProcess | null = null
let lastContext: Context = {}

function readEnv(path: string): Record<string, string> {
  if (!existsSync(path)) return {}
  return Object.fromEntries(
    readFileSync(path, 'utf8').split('\n').filter((l) => l.includes('=') && !l.trimStart().startsWith('#'))
      .map((l) => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim().replace(/^['"]|['"]$/g, '')]),
  )
}

function startBackend() {
  if (env.BIZOS_BACKEND_URL) return // remote backend (Docker / Cloud Run)
  backend = spawn('uv', ['run', 'uvicorn', 'bizos.main:app', '--host', '127.0.0.1', '--port', '8787'], {
    cwd: join(ROOT, 'app/backend'), env: { ...process.env, BIZOS_TOKEN: config.token }, stdio: 'inherit',
  })
  backend.on('error', (e) => console.error('[bizos] backend failed to start (is uv installed?)', e.message))
}

// Hands-free: an offline "Hey BizOS" listener in its own process (see backend/bizos/wake.py). Only "wake" comes out.
let wake: ChildProcess | null = null
let wakeStatus: 'off' | 'starting' | 'on' = 'off'
const handsFree = (status: typeof wakeStatus, error?: string) => {
  wakeStatus = status
  overlay?.webContents.send('hands-free', status, error)
}
function startWake() {
  if (wake) return
  handsFree('starting')
  const proc = spawn('uv', ['run', 'python', '-m', 'bizos.wake'], { cwd: join(ROOT, 'app/backend'), stdio: ['ignore', 'pipe', 'inherit'] })
  wake = proc
  let error = ''
  createInterface({ input: proc.stdout! }).on('line', (line) => {
    if (line !== 'wake') console.log(`[bizos] hands-free: ${line}`)
    else console.log('[bizos] hands-free: heard "Hey BizOS"')
    if (line === 'wake') speaker.stop() // talking over BizOS interrupts it
    if (line === 'wake') void summon().then(() => overlay?.webContents.send('wake'))
    else if (line === 'status listening') handsFree('on')
    else if (line.startsWith('error ')) error = line.slice(6)
  })
  proc.on('error', (e) => { error = e.message })
  proc.on('exit', () => {
    if (wake === proc) wake = null
    handsFree('off', error || undefined)
  })
}
const stopWake = () => { wake?.kill(); wake = null }

function load(win: BrowserWindow, hash = '') {
  const dev = process.env.ELECTRON_RENDERER_URL
  if (dev) win.loadURL(`${dev}#${hash}`)
  else win.loadFile(join(HERE, '../renderer/index.html'), { hash })
}

function harden(win: BrowserWindow) {
  // Model output and screen text are untrusted: links leave the app, never navigate it.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith(process.env.ELECTRON_RENDERER_URL ?? 'file://')) e.preventDefault()
  })
}

const prefs = { preload: join(HERE, '../preload/index.cjs'), sandbox: true, contextIsolation: true, nodeIntegration: false }

function createOverlay() {
  const { workArea } = screen.getPrimaryDisplay()
  overlay = new BrowserWindow({
    ...SIZE, x: Math.round(workArea.x + (workArea.width - SIZE.width) / 2), y: workArea.y + 10,
    transparent: true, frame: false, resizable: false, hasShadow: false, skipTaskbar: true, fullscreenable: false,
    alwaysOnTop: true, show: false, backgroundColor: '#00000000',
    ...(process.platform === 'darwin' ? { type: 'panel' } : {}), // non-activating: the user's app stays frontmost
    webPreferences: prefs,
  })
  // No setContentProtection: the overlay stays visible to screen sharing on purpose.
  overlay.setAlwaysOnTop(true, 'screen-saver')
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  overlay.setIgnoreMouseEvents(true, { forward: true })
  harden(overlay)
  overlay.once('ready-to-show', () => overlay?.showInactive())
  load(overlay, '/overlay')
}

let openId = ''
function openWorkspace(id: string) {
  if (workspace && !workspace.isDestroyed() && openId === id) {
    workspace.show() // same workspace: it live-updates itself as the agent edits it
    return
  }
  openId = id
  if (!workspace || workspace.isDestroyed()) {
    workspace = new BrowserWindow({
      width: 1480, height: 940, minWidth: 1080, minHeight: 700, show: false, title: 'BizOS Workspace',
      backgroundColor: '#F3F0E8', titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
      trafficLightPosition: { x: 18, y: 20 }, icon: ICON, webPreferences: prefs,
    })
    harden(workspace)
    workspace.once('ready-to-show', () => workspace?.show())
  } else workspace.focus()
  load(workspace, `/w/${id}`)
}

async function summon() {
  let ctx = await sense.read(await clipboard.readText())
  if (!ctx.app || /^(BizOS|Electron)$/.test(ctx.app)) ctx = lastContext
  lastContext = ctx
  const off = !!ctx.app && settings.muted.includes(ctx.app)
  overlay?.webContents.send('summon', off ? { app: ctx.app, off } : ctx) // muted apps: nothing leaves main
  overlay?.setIgnoreMouseEvents(false)
  overlay?.show()
  overlay?.focus()
}

ipcMain.handle('config', () => config)
ipcMain.handle('capture', () => sense.capture())
ipcMain.on('summon', () => void summon())
ipcMain.on('interactive', (_e, on: boolean) => overlay?.setIgnoreMouseEvents(!on, { forward: true }))
ipcMain.on('dismiss', () => {
  overlay?.setIgnoreMouseEvents(true, { forward: true })
  overlay?.blur()
})
// Drag: native drag regions don't work in a click-through panel. The grip sends its pointer offset; no offset = start.
let origin = [0, 0]
ipcMain.on('drag', (_e, dx?: number, dy?: number) => {
  if (!overlay) return
  if (dx === undefined || dy === undefined) origin = overlay.getPosition()
  else overlay.setPosition(Math.round(origin[0] + dx), Math.round(origin[1] + dy))
})
// Give the keyboard back to the user's app: this is also what ends a macOS dictation (blurring the field doesn't).
ipcMain.on('release', () => overlay?.blur())
ipcMain.on('workspace',(_e, id: string) => /^[a-f0-9]{1,32}$/.test(id) && openWorkspace(id))
ipcMain.on('external', (_e, url: string) => /^https?:\/\//.test(url) && shell.openExternal(url))
// Pairing must happen in Chrome (where the extension lives), not whatever the default browser is.
ipcMain.on('open-in-chrome', (_e, url: string) => {
  if (!/^http:\/\/127\.0\.0\.1:8787\/pair\?code=/.test(url)) return
  if (process.platform === 'darwin') spawn('open', ['-a', 'Google Chrome', url]).on('error', () => shell.openExternal(url))
  else spawn('cmd', ['/c', 'start', 'chrome', url]).on('error', () => shell.openExternal(url)) // untested
})
ipcMain.handle('settings', () => ({ ...settings, handsFreeStatus: wakeStatus }))
ipcMain.handle('desktop', async (_e, op: string, args: Record<string, string>) => {
  try {
    return { ok: true, result: await desktop(op, args) }
  } catch (e) {
    return { ok: false, error: String((e as Error).message) }
  }
})
ipcMain.on('mute', (_e, appName: string, off = true) => {
  settings.muted = settings.muted.filter((a) => a !== appName).concat(off ? [appName] : [])
  saveSettings()
  if (!off) void summon() // read the app again now that it's allowed
})
ipcMain.handle('speak', (_e, text: string) => speaker.speak(String(text).slice(0, 600)))
ipcMain.on('stop-speaking', () => speaker.stop())
ipcMain.on('hands-free', (_e, on: boolean) => {
  settings.handsFree = !!on
  saveSettings()
  if (on) startWake()
  else stopWake()
})
ipcMain.on('always-capture',(_e, on: boolean) => {
  settings.alwaysCapture = !!on
  saveSettings()
})
ipcMain.handle('dictate', async () => {
  // Dictation types into the key window of the ACTIVE app; the overlay is a non-activating panel, so activate first.
  // Activation is asynchronous and sometimes needs a second nudge; dictation started before it lands goes nowhere.
  for (let i = 0; i < 10 && !overlay?.isFocused(); i++) {
    app.focus({ steal: true })
    overlay?.focus()
    await new Promise((r) => setTimeout(r, 60))
  }
  overlay?.webContents.focus()
  console.log(`[bizos] dictation: starting (overlay focused: ${overlay?.isFocused()})`)
  await new Promise((r) => setTimeout(r, 200))
  try {
    await voice()
    return null
  } catch (e) {
    return String((e as Error).message)
  }
})

app.whenReady().then(() => {
  try {
    settings = { ...settings, ...JSON.parse(readFileSync(settingsFile(), 'utf8')) }
  } catch {
    /* first run: defaults */
  }
  if (process.platform === 'darwin' && existsSync(ICON)) app.dock?.setIcon(nativeImage.createFromPath(ICON))
  startBackend()
  createOverlay()
  if (settings.handsFree) overlay?.webContents.once('did-finish-load', startWake)
  if (!globalShortcut.register(HOTKEY, () => void summon())) console.error(`[bizos] hotkey ${HOTKEY} is taken`)
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  backend?.kill()
  stopWake()
  speaker.stop()
})
app.on('window-all-closed', () => process.platform !== 'darwin' && app.quit())
