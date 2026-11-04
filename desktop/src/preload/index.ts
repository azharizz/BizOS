import { contextBridge, ipcRenderer } from 'electron'
import type { Bridge } from '../shared/types'

const bridge: Bridge = {
  config: () => ipcRenderer.invoke('config'),
  onSummon: (fn) => void ipcRenderer.on('summon', (_e, ctx) => fn(ctx)),
  summon: () => ipcRenderer.send('summon'),
  setInteractive: (on) => ipcRenderer.send('interactive', on),
  dismiss: () => ipcRenderer.send('dismiss'),
  quit: () => ipcRenderer.send('quit'),
  release: () => ipcRenderer.send('release'),
  drag: (dx, dy) => ipcRenderer.send('drag', dx, dy),
  capture: () => ipcRenderer.invoke('capture'),
  openWorkspace: (id) => ipcRenderer.send('workspace', id),
  muteApp: (app, off) => ipcRenderer.send('mute', app, off),
  settings: () => ipcRenderer.invoke('settings'),
  setAlwaysCapture: (on) => ipcRenderer.send('always-capture', on),
  dictate: () => ipcRenderer.invoke('dictate'),
  setHandsFree: (on) => ipcRenderer.send('hands-free', on),
  speak: (text) => ipcRenderer.invoke('speak', text),
  stopSpeaking: () => ipcRenderer.send('stop-speaking'),
  onHandsFree: (fn) => void ipcRenderer.on('hands-free', (_e, status, error) => fn(status, error)),
  onWake: (fn) => void ipcRenderer.on('wake', () => fn()),
  onStop: (fn) => void ipcRenderer.on('stop', () => fn()),
  desktop: (op, args) => ipcRenderer.invoke('desktop', op, args),
  openExternal: (url) => ipcRenderer.send('external', url),
  askOverlay: (goal) => ipcRenderer.send('ask', goal),
  onAsk: (fn) => void ipcRenderer.on('ask', (_e, goal) => fn(goal)),
  openInChrome: (url) => ipcRenderer.send('open-in-chrome', url),
}

contextBridge.exposeInMainWorld('bizos', bridge)
