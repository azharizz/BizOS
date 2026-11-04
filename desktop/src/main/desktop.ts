/**
 * Desktop actions the agent can request (via the overlay): open an app or a link, read the screen, write a note.
 * No clicking or typing in other apps: a note is always a NEW document, created through the app's own scripting.
 * Inputs are validated and passed as arguments, never through a shell or spliced into a script.
 */
import { clipboard, shell } from 'electron'
import { execFile } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Context } from '../shared/types'
import { sendKeys, winControl } from './control-win'

const WIN = process.platform === 'win32' // app control: macOS UI scripting, or Windows UI Automation (control-win.ts)

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

// ---------------- Mac control (System Events UI scripting; needs Accessibility permission once)
// Shells, password stores, system settings and BizOS itself are never operated: those are the places where a
// misread instruction could do the most damage. (Finder is allowed: moving to Trash and Cmd+Delete are asked first.)
const NEVER_OPERATE = new RegExp('^(terminal|iterm2?|ghostty|warp|alacritty|kitty|hyper|keychain access|passwords|1password.*|bitwarden|' +
  'system settings|system preferences|script editor|automator|shortcuts|bizos|electron|loginwindow|' +
  // Windows: shells, the registry, Task Manager, Settings, the credential store
  'powershell|pwsh|cmd|command prompt|windows terminal|wt|regedit|registry editor|task manager|taskmgr|control panel|settings|credential manager)$', 'i')

export function controllable(name: string): string {
  const app = checkApp(name.trim())
  if (NEVER_OPERATE.test(app)) throw new Error(`BizOS won't operate ${app}`)
  return app
}

const KEYS: Record<string, number> = {
  return: 36, enter: 76, tab: 48, space: 49, delete: 51, backspace: 51, escape: 53, esc: 53, forwarddelete: 117,
  left: 123, right: 124, down: 125, up: 126, home: 115, end: 119, pageup: 116, pagedown: 121,
}
export function keyCode(name: string): number {
  const code = KEYS[name.toLowerCase().replace(/[\s_-]/g, '')]
  if (code === undefined) throw new Error(`unknown key ${name.slice(0, 20)}`)
  return code
}
const MODS: Record<string, string> = { cmd: 'command', command: 'command', shift: 'shift', option: 'option', alt: 'option', ctrl: 'control', control: 'control' }
export function modifiers(list: string[] = []): string {
  if (!list.length) return ''
  return '{' + list.map((m) => {
    const x = MODS[m.toLowerCase()]
    if (!x) throw new Error(`unknown modifier ${m.slice(0, 20)}`)
    return `${x} down`
  }).join(', ') + '}'
}

const ROLES: Record<string, string> = {
  AXButton: 'button', AXTextField: 'text field', AXTextArea: 'text area', AXCheckBox: 'checkbox', AXRadioButton: 'radio',
  AXStaticText: 'text', AXPopUpButton: 'pop-up', AXMenuButton: 'menu button',
  // Windows UI Automation control types
  Button: 'button', Edit: 'text field', Document: 'text area', CheckBox: 'checkbox', RadioButton: 'radio', ComboBox: 'combo box',
  Hyperlink: 'link', TabItem: 'tab', MenuItem: 'menu item', ListItem: 'list item', Text: 'text', AXLink: 'link', AXTab: 'tab', AXComboBox: 'combo box', AXSearchField: 'search field',
}
export function parseElements(out: string) {
  return out.split('\n').filter((l) => l.includes('\t')).map((l, ref) => {
    const [role, name] = l.split('\t')
    return { ref, role: ROLES[role] ?? role, name: (name ?? '').trim() }
  })
}

const ACCESSIBILITY = 'ACCESSIBILITY: allow BizOS in System Settings → Privacy & Security → Accessibility'
const osa = (script: string, ...args: string[]) =>
  new Promise<string>((resolve, reject) => execFile('osascript', ['-e', `on run argv\n${script}\nend run`, ...args],
    { timeout: 25_000 }, (e, out, err) => {
      if (!e) return resolve(String(out))
      const msg = String(err || e.message)
      reject(new Error(/-25211|not allowed assistive|NO-WINDOW/.test(msg) ? ACCESSIBILITY
        : msg.trim().split('\n')[0].replace(/^\d+:\d+: execution error: /, '')))
    }))

// Walks the front window once and lists (or clicks) the controls; capped so a huge window can't stall it.
// Without Accessibility permission System Events sees no windows at all, hence NO-WINDOW -> ask for permission.
const WALK = `set appName to item 1 of argv
set target to item 2 of argv
tell application appName to activate
delay 0.4
tell application "System Events"
tell process appName
  if (count of windows) is 0 then error "NO-WINDOW"
  set out to ""
  set n to 0
  set els to entire contents of front window
  repeat with i from 1 to (count of els)
    set e to item i of els
    try
      set r to role of e
      if r is "AXStaticText" and target is "" then
        try
          set v to (value of e) as text
          if v is not "missing value" and v is not "" then
            set out to out & r & tab & v & linefeed
            set n to n + 1
          end if
        end try
      else if r is in {"AXButton","AXTextField","AXTextArea","AXCheckBox","AXRadioButton","AXPopUpButton","AXMenuButton","AXLink","AXTab","AXComboBox","AXSearchField"} then
        set nm to ""
        try
          set nm to (name of e) as text
        end try
        if nm is "missing value" or nm is "" then
          try
            set nm to (description of e) as text
          end try
        end if
        if nm is "missing value" then set nm to ""
        if nm is "" or nm is "button" then
          try
            set nm to (value of attribute "AXIdentifier" of e) as text
          end try
          if nm is "missing value" then set nm to ""
        end if
        if target is not "" and nm is target then
          click e
          return "clicked" & tab & r
        end if
        set out to out & r & tab & nm & linefeed
        set n to n + 1
        if n > 150 then exit repeat
      end if
    end try
  end repeat
  if target is not "" then error "no control named " & target
  return out
end tell
end tell`

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
    // ---- Mac control
    async ui_read({ app }) {
      const a = controllable(app)
      return { app, elements: parseElements(WIN ? await winControl.read(a) : await osa(WALK, a, '')) }
    },
    async ui_click({ app, name }) {
      if (!name?.trim()) throw new Error('which control? give its name from ui_read')
      const a = controllable(app)
      const [, role] = (WIN ? await winControl.click(a, name.trim()) : await osa(WALK, a, name.trim())).trim().split('\t')
      return { app, clicked: name, role: ROLES[role] ?? role }
    },
    async ui_menu({ app, menu, item }) {
      if (WIN) {
        await winControl.menu(controllable(app), String(menu), String(item))
        return { app, menu, item }
      }
      await osa(`tell application (item 1 of argv) to activate
delay 0.3
tell application "System Events" to tell process (item 1 of argv) to click menu item (item 3 of argv) of menu (item 2 of argv) of menu bar 1`,
      controllable(app), String(menu), String(item))
      return { app, menu, item }
    },
    // Typing goes through the clipboard (paste): exact text in any language, then the old clipboard is put back.
    async type_text({ app, text }) {
      if (!text || text.length > 5000) throw new Error('text must be 1-5,000 characters')
      const before = await clipboard.readText() // async in Electron 45
      clipboard.writeText(text)
      try {
        if (WIN) await winControl.paste(controllable(app))
        else await osa('tell application (item 1 of argv) to activate\ndelay 0.3\ntell application "System Events" to keystroke "v" using command down', controllable(app))
        await new Promise((r) => setTimeout(r, 250))
      } finally {
        clipboard.writeText(before)
      }
      return { app, typed: text.length }
    },
    async press_key({ app, key, modifiers: mods }) {
      const list = mods ? String(mods).split(',').map((m) => m.trim()).filter(Boolean) : []
      if (WIN) {
        await winControl.keys(controllable(app), sendKeys(key ?? '', list))
        return { app, pressed: [...list, key].join('+') }
      }
      const using = modifiers(list)
      const single = /^[a-z0-9]$/i.test(key ?? '')
      const press = single ? 'keystroke (item 2 of argv)' : `key code ${keyCode(key ?? '')}`
      await osa(`tell application (item 1 of argv) to activate\ndelay 0.2\ntell application "System Events" to ${press}${using ? ` using ${using}` : ''}`,
        controllable(app), single ? key.toLowerCase() : '')
      return { app, pressed: [...list, key].join('+') }
    },
    async run_shortcut({ name, input }) {
      if (!/^[\p{L}\p{N} .&+'()-]{1,80}$/u.test(name ?? '')) throw new Error('not a shortcut name')
      if (WIN) return { shortcut: name, output: (await winControl.runShortcut(name, input)).slice(0, 4000) }
      const out = await new Promise<string>((resolve, reject) => {
        const p = execFile('shortcuts', ['run', name, ...(input ? ['--input-path', '-'] : [])], { timeout: 60_000 },
          (e, o, err) => (e ? reject(new Error(String(err || e.message).trim().split('\n')[0])) : resolve(String(o))))
        if (input) p.stdin?.end(String(input))
      })
      return { shortcut: name, output: out.slice(0, 4000) }
    },
    async list_shortcuts() {
      if (WIN) return { shortcuts: winControl.listShortcuts(), folder: 'BizOS Shortcuts (in your user folder)' }
      const out = await new Promise<string>((resolve, reject) =>
        execFile('shortcuts', ['list'], { timeout: 15_000 }, (e, o) => (e ? reject(e) : resolve(String(o)))))
      return { shortcuts: out.split('\n').filter(Boolean).slice(0, 200) }
    },
    clipboard_read: async () => ({ text: (await clipboard.readText()).slice(0, 8000) }),
    async clipboard_write({ text }) {
      clipboard.writeText(String(text ?? '').slice(0, 20_000))
      return { written: String(text ?? '').length }
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
