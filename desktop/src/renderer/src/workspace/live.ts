/**
 * The workspace meta the window last fetched (plan, actions, brief), for BizOS's own widgets inside AG Studio.
 * Those widgets render deep inside AG Studio, so they read it from here (useSyncExternalStore), not from React context.
 */
import { useSyncExternalStore } from 'react'
import type { WorkspaceMeta } from './types'

let meta: WorkspaceMeta | null = null
const subs = new Set<() => void>()

export function setLive(m: WorkspaceMeta) {
  meta = m
  subs.forEach((fn) => fn())
}

export const useLive = () => useSyncExternalStore((fn) => (subs.add(fn), () => void subs.delete(fn)), () => meta)
