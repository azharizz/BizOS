import { execFile } from 'node:child_process'
import type { Context } from '../../shared/types'

/** Run an OS helper with a hard timeout. Sensing is best effort: failures read as empty. */
export const run = (cmd: string, args: string[], timeout = 2500) =>
  new Promise<string>((resolve) => execFile(cmd, args, { timeout, maxBuffer: 1 << 20 }, (_e, out) => resolve(out ?? '')))

export function clean(ctx: Record<string, unknown>): Context {
  return Object.fromEntries(
    Object.entries(ctx).filter(([, v]) => typeof v === 'string' && v.trim()).map(([k, v]) => [k, (v as string).trim().slice(0, 6000)]),
  )
}
