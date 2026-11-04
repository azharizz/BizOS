/**
 * Screen Context Engine: one interface, one adapter per OS (factory).
 *   read()    L1 + L2: app, window title, URL, selection, clipboard, on-screen text
 *   capture() L3: a screenshot. Only call after the user said yes.
 */
import type { Context } from '../../shared/types'
import { readMac } from './mac'
import { readWin } from './win'

export interface Sense {
  read: (clipboard: string) => Promise<Context>
  capture: () => Promise<string | null>
}

const ADAPTERS: Record<string, Sense['read']> = { darwin: readMac, win32: readWin }

async function capture(): Promise<string | null> {
  const { desktopCapturer, screen } = await import('electron')
  const { width, height } = screen.getPrimaryDisplay().size
  const [src] = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: Math.min(width, 1600), height: Math.min(height, 1000) } })
  return src && !src.thumbnail.isEmpty() ? src.thumbnail.toPNG().toString('base64') : null
}

export function createSense(platform: string): Sense {
  const read = ADAPTERS[platform]
  if (!read) throw new Error(`BizOS sensing is not supported on ${platform}`)
  return { read, capture }
}
