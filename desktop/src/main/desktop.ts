/**
 * Desktop actions the agent can request (via the overlay): open an app or a link, read the screen, write a note.
 * No clicking or typing in other apps: a note is always a NEW document, created through the app's own scripting.
 * Inputs are validated and passed as arguments, never through a shell or spliced into a script.
 */
import { shell } from 'electron'
import { execFile } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Context } from '../shared/types'

/** Which notes app to write into. "Notepad" on a Mac means TextEdit. */
export function noteApp(name: string, platform: string): 'TextEdit' | 'Notes' | 'Notepad' {
  const n = name.toLowerCase()
  if (platform === 'win32') {
    if (!n || /notepad|text/.test(n)) return 'Notepad'
  } else if (!n || /notepad|textedit|text edit/.test(n)) return 'TextEdit'
  else if (/notes/.test(n)) return 'Notes'
  throw new Error(`can only write notes into ${platform === 'win32' ? 'Notepad' : 'TextEdit or Notes'}, not ${name.slice(0, 40)}`)
}

const NEVER_CLOSE = /^(finder|dock|system ?settings|system ?preferences|systemuiserver|loginwindow|bizos|electron)$/i

/** The app to quit. "Notepad" on a Mac means TextEdit; the system and BizOS itself are off limits. */
export function closeTarget(name: string, platform: string): string {
  const app = checkApp(name.trim())
  if (NEVER_CLOSE.test(app)) throw new Error(`BizOS won't close ${app}`)
  return platform !== 'win32' && /notepad/i.test(app) ? 'TextEdit' : app
}

export const notesHtml =(text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')

const exec = (cmd: string, args: string[]) =>
  new Promise<void>((resolve, reject) => execFile(cmd, args, (e, _out, err) => {
    if (!e) return resolve()
    reject(new Error(/-1743|not authori[sz]ed/i.test(String(err))
      ? 'macOS blocked BizOS from controlling that app: allow it in System Settings → Privacy & Security → Automation'
      : String(err || e.message).trim().split('\n')[0]))
  }))

// The text is `item 1 of argv`: AppleScript never sees it as code.
const NEW_DOC: Record<string, string> = {
  // Create first, then bring forward (activating first makes TextEdit open an extra blank document).
  TextEdit: 'tell application "TextEdit"\nmake new document with properties {text:item 1 of argv}\nactivate\nend tell',
  Notes: 'tell application "Notes"\nshow (make new note with properties {body:item 1 of argv})\nactivate\nend tell',
}

async function writeNote(app: ReturnType<typeof noteApp>, text: string) {
  if (app === 'Notepad') { // Windows, untested: a temp file opened in Notepad
    const file = join(tmpdir(), `bizos-note-${Date.now()}.txt`)
    writeFileSync(file, text)
    return exec('notepad.exe', [file])
  }
  return exec('osascript', ['-e', `on run argv\n${NEW_DOC[app]}\nend run`, app === 'Notes' ? notesHtml(text) : text])
}

export function checkApp(name: string): string {
  if (!/^[\p{L}\p{N} .&+'()-]{1,60}$/u.test(name) || name.includes('..')) throw new Error(`not an app name: ${name.slice(0, 40)}`)
  return name
}

export function checkUrl(url: string): string {
  if (!/^https?:\/\/[^\s]+$/.test(url)) throw new Error('only http(s) links can be opened')
  return url
}

const launch = (name: string) =>
  new Promise<void>((resolve, reject) => {
    const [cmd, args] = process.platform === 'darwin' ? ['open', ['-a', name]] : ['cmd', ['/c', 'start', '""', name]] // Windows untested
    execFile(cmd, args, (e) => (e ? reject(new Error(`could not open ${name}`)) : resolve()))
  })

export function createDesktop(read: () => Promise<Context>) {
  const ops: Record<string, (args: Record<string, string>) => Promise<unknown>> = {
    async open_app({ name }) {
      await launch(checkApp(name))
      await new Promise((r) => setTimeout(r, 1500)) // let its window come forward, then read it
      return { app: name, ...(await read()) }
    },
    async open_url({ url }) {
      await shell.openExternal(checkUrl(url))
      return { opened: url }
    },
    read_screen: () => read(),
    // discard="yes": quit WITHOUT saving (the user asked for it; the plan step was approved by a click).
    // Otherwise the app quits normally and asks about unsaved changes itself.
    async close_app({ name, discard }) {
      const app = closeTarget(name ?? '', process.platform)
      const drop = discard === 'yes'
      if (process.platform === 'win32') { // untested: taskkill without /F lets the app prompt; /F discards
        await exec('taskkill', ['/IM', `${app.replace(/\s+/g, '')}.exe`, ...(drop ? ['/F'] : [])])
      } else {
        await exec('osascript', ['-e', `on run argv\ntell application (item 1 of argv) to quit${drop ? ' saving no' : ''}\nend run`, app])
      }
      return { app, closed: true, discarded: drop }
    },
    async write_note({ app, text }) {
      const target = noteApp(app ?? '', process.platform)
      if (!text?.trim() || text.length > 20_000) throw new Error('note text must be 1-20,000 characters')
      await writeNote(target, text)
      return { app: target, written: text.length }
    },
  }
  return async (op: string, args: Record<string, string>) => {
    if (!ops[op]) throw new Error(`unknown desktop action ${op}`)
    return ops[op](args ?? {})
  }
}
