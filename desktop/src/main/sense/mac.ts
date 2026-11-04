import type { Context } from '../../shared/types'
import { clean, run } from './run'

const SEP = '\u001f'
const FIELDS = ['app', 'title', 'url', 'selection', 'text'] as const
const CHROMIUM = ['Google Chrome', 'Brave Browser', 'Microsoft Edge', 'Arc', 'Chromium', 'Vivaldi']
const PAGE_TEXT = 'document.body.innerText.slice(0, 6000)'

// L1 (app, window title, selection) + L2 fallback (visible static text) through the Accessibility API.
const FRONT = `
set sep to (ASCII character 31)
tell application "System Events"
  set p to first application process whose frontmost is true
  set appName to name of p
  set t to ""
  set s to ""
  set body to ""
  try
    set t to value of attribute "AXTitle" of (value of attribute "AXFocusedWindow" of p)
  end try
  try
    set s to value of attribute "AXSelectedText" of (value of attribute "AXFocusedUIElement" of p)
  end try
  try
    set AppleScript's text item delimiters to " "
    set body to (value of every static text of front window of p) as text
  end try
end tell
return appName & sep & t & sep & "" & sep & s & sep & body`

// Browser URL (L1) and page text (L2). Page text needs "Allow JavaScript from Apple Events", so it may be empty.
const browser = (app: string) =>
  app === 'Safari'
    ? `set sep to (ASCII character 31)
tell application "Safari"
  set u to URL of front document
  set b to ""
  try
    set b to do JavaScript "${PAGE_TEXT}" in front document
  end try
  return u & sep & b
end tell`
    : `set sep to (ASCII character 31)
tell application "${app}"
  set u to URL of active tab of front window
  set b to ""
  try
    set b to execute active tab of front window javascript "${PAGE_TEXT}"
  end try
  return u & sep & b
end tell`

export function parseMac(stdout: string, clipboard: string): Context {
  const parts = stdout.replace(/\n$/, '').split(SEP)
  const ctx: Context = {}
  FIELDS.forEach((k, i) => (ctx[k] = parts[i]))
  return clean({ ...ctx, clipboard })
}

export async function readMac(clipboard: string): Promise<Context> {
  const ctx = parseMac(await run('osascript', ['-e', FRONT]), clipboard)
  if (ctx.app && (ctx.app === 'Safari' || CHROMIUM.includes(ctx.app))) {
    const [url, body] = (await run('osascript', ['-e', browser(ctx.app)])).replace(/\n$/, '').split(SEP)
    return clean({ ...ctx, url, text: body || ctx.text })
  }
  return ctx
}
