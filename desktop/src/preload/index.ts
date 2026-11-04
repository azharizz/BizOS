import { contextBridge, ipcRenderer } from 'electron'
import type { Bridge } from '../shared/types'

const bridge: Bridge = {
  config: () => ipcRenderer.invoke('config'),
  onSummon: (fn) => void ipcRenderer.on('summon', (_e, ctx) => fn(ctx)),
  summon: () => ipcRenderer.send('summon'),
  setInteractive: (on) => ipcRenderer.send('interactive', on),
  dismiss: () => ipcRenderer.send('dismiss'),
  release: () => ipcRenderer.send('release'),
  drag: (dx, dy) => ipcRenderer.send('drag', dx, dy),
  capture: () => ipcRenderer.invoke('capture'),
  openWorkspace: (id) => ipcRenderer.send('workspace', id),
  muteApp: (app, off) => ipcRenderer.send('mute', app, off),
  settings: () => ipcRenderer.invoke('settings'),
  setAlwaysCapture: (on) => ipcRenderer.send('always-capture', on),
  dictate: () => ipcRenderer.invoke('dictate'),
  setHandsFree: (on) => ipcRenderer.send('hands-free', on),
  onHandsFree: (fn) => void ipcRenderer.on('hands-free', (_e, status, error) => fn(status, error)),
  onWake: (fn) => void ipcRenderer.on('wake', () => fn()),
  desktop: (op, args) => ipcRenderer.invoke('desktop', op, args),
  openExternal: (url) => ipcRenderer.send('external', url),
  openInChrome: (url) => ipcRenderer.send('open-in-chrome', url),
}

contextBridge.exposeInMainWorld('bizos', bridge)
