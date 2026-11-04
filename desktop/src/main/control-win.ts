/**
 * App control on Windows: the alternative to macOS UI scripting. UNTESTED: written alongside macOS, never run on a PC.
 *   read / click / menus  Windows UI Automation (System.Windows.Automation) through PowerShell
 *   keys / typing         SendKeys (typing pastes from the clipboard, like on macOS)
 *   Shortcuts             a "BizOS Shortcuts" folder in your user folder: put shortcuts (.lnk, .url) or your own
 *                         scripts (.bat, .cmd, .ps1) there; the agent can list them and run one by name (always asked)
 * Every argument reaches PowerShell as an environment variable, never as part of the script.
 */
import { execFile } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { extname, join } from 'node:path'
import { shell } from 'electron'

export const SHORTCUTS_DIR = join(homedir(), 'BizOS Shortcuts')
const RUNNABLE = ['.lnk', '.url', '.bat', '.cmd', '.ps1']

const SPECIAL: Record<string, string> = {
  return: '{ENTER}', enter: '{ENTER}', tab: '{TAB}', space: ' ', delete: '{BACKSPACE}', backspace: '{BACKSPACE}',
  forwarddelete: '{DEL}', escape: '{ESC}', esc: '{ESC}', left: '{LEFT}', right: '{RIGHT}', up: '{UP}', down: '{DOWN}',
  home: '{HOME}', end: '{END}', pageup: '{PGUP}', pagedown: '{PGDN}',
}
const MOD: Record<string, string> = { cmd: '^', command: '^', ctrl: '^', control: '^', shift: '+', alt: '%', option: '%' }

/** A key (+ modifiers) as a SendKeys string. "cmd" means Ctrl, so the agent can use the same names as on a Mac. */
export function sendKeys(key: string, mods: string[] = []): string {
  const k = key.toLowerCase().replace(/[\s_-]/g, '')
  const base = SPECIAL[k] ?? (/^[a-z0-9]$/.test(k) ? k : null)
  if (base === null) throw new Error(`unknown key ${key.slice(0, 20)}`)
  return mods.map((m) => {
    const x = MOD[m.toLowerCase()]
    if (!x) throw new Error(`unknown modifier ${m.slice(0, 20)}`)
    return x
  }).join('') + base
}

/** The runnable file in the shortcuts folder whose name (without extension) is `name`, ignoring case. */
export function findShortcut(files: string[], name: string): string | null {
  const want = name.trim().toLowerCase()
  return files.find((f) => RUNNABLE.includes(extname(f).toLowerCase()) && f.slice(0, -extname(f).length).toLowerCase() === want) ?? null
}

// ---- PowerShell: find the app's main window, then act on it with UI Automation
const PRELUDE = `$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
Add-Type @"
using System; using System.Runtime.InteropServices;
public class BW {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
}
"@
$name = $env:BIZOS_APP
$words = @($name) + ($name -split '\\s+' | Where-Object { $_.Length -gt 3 })
$proc = $null
foreach ($w in $words) {
  $proc = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and ($_.ProcessName -like "*$w*" -or $_.MainWindowTitle -like "*$w*" -or $_.Description -like "*$w*") } | Select-Object -First 1
  if ($proc) { break }
}
if (-not $proc) { throw "no open window for $name: open it first" }
[void][BW]::ShowWindow($proc.MainWindowHandle, 9)
[void][BW]::SetForegroundWindow($proc.MainWindowHandle)
Start-Sleep -Milliseconds 300
$A = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$root = $A::FromHandle($proc.MainWindowHandle)
function Find-Named($scope, $label) {
  $c = New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $label)
  return $scope.FindFirst($TS::Descendants, $c)
}
function Press($e) {
  foreach ($p in @([System.Windows.Automation.InvokePattern]::Pattern, [System.Windows.Automation.TogglePattern]::Pattern,
                   [System.Windows.Automation.SelectionItemPattern]::Pattern, [System.Windows.Automation.ExpandCollapsePattern]::Pattern)) {
    $o = $null
    if ($e.TryGetCurrentPattern($p, [ref]$o)) {
      if ($o -is [System.Windows.Automation.InvokePattern]) { $o.Invoke() }
      elseif ($o -is [System.Windows.Automation.TogglePattern]) { $o.Toggle() }
      elseif ($o -is [System.Windows.Automation.SelectionItemPattern]) { $o.Select() }
      else { $o.Expand() }
      return
    }
  }
  $e.SetFocus()
}
`

const SCRIPTS = {
  read: `${PRELUDE}
$keep = 'Button','Edit','CheckBox','RadioButton','ComboBox','Hyperlink','TabItem','MenuItem','ListItem','Text','Document'
$n = 0
foreach ($e in $root.FindAll($TS::Descendants, [System.Windows.Automation.Condition]::TrueCondition)) {
  $t = $e.Current.ControlType.ProgrammaticName -replace '^ControlType\\.', ''
  if ($keep -contains $t -and $e.Current.Name) { "$t\`t$($e.Current.Name)"; $n++ }
  if ($n -ge 150) { break }
}`,
  click: `${PRELUDE}
$e = Find-Named $root $env:BIZOS_NAME
if (-not $e) { throw "no control named $($env:BIZOS_NAME)" }
Press $e
"clicked\`t$($e.Current.ControlType.ProgrammaticName -replace '^ControlType\\.', '')"`,
  menu: `${PRELUDE}
$m = Find-Named $root $env:BIZOS_MENU
if (-not $m) { throw "no menu named $($env:BIZOS_MENU)" }
Press $m
Start-Sleep -Milliseconds 350
$i = Find-Named $A::RootElement $env:BIZOS_ITEM
if (-not $i) { throw "no menu item named $($env:BIZOS_ITEM)" }
Press $i`,
  keys: `${PRELUDE}
[System.Windows.Forms.SendKeys]::SendWait($env:BIZOS_KEYS)`,
}

const ps = (script: string, env: Record<string, string>) =>
  new Promise<string>((resolve, reject) => execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script],
    { timeout: 30_000, maxBuffer: 1 << 20, env: { ...process.env, ...env } },
    (e, out, err) => (e ? reject(new Error(String(err || e.message).trim().split('\n')[0])) : resolve(String(out)))))

export const winControl = {
  read: (app: string) => ps(SCRIPTS.read, { BIZOS_APP: app }),
  click: (app: string, name: string) => ps(SCRIPTS.click, { BIZOS_APP: app, BIZOS_NAME: name }),
  menu: (app: string, menu: string, item: string) => ps(SCRIPTS.menu, { BIZOS_APP: app, BIZOS_MENU: menu, BIZOS_ITEM: item }),
  keys: (app: string, keys: string) => ps(SCRIPTS.keys, { BIZOS_APP: app, BIZOS_KEYS: keys }),
  paste: (app: string) => ps(SCRIPTS.keys, { BIZOS_APP: app, BIZOS_KEYS: '^v' }),
  listShortcuts(): string[] {
    try {
      return readdirSync(SHORTCUTS_DIR).filter((f) => RUNNABLE.includes(extname(f).toLowerCase())).map((f) => f.slice(0, -extname(f).length))
    } catch {
      return [] // no folder yet
    }
  },
  async runShortcut(name: string, input = ''): Promise<string> {
    let files: string[] = []
    try { files = readdirSync(SHORTCUTS_DIR) } catch { /* none */ }
    const file = findShortcut(files, name)
    if (!file) throw new Error(`no shortcut "${name}" in ${SHORTCUTS_DIR}`)
    const path = join(SHORTCUTS_DIR, file)
    const ext = extname(file).toLowerCase()
    if (ext === '.lnk' || ext === '.url') {
      const err = await shell.openPath(path)
      if (err) throw new Error(err)
      return ''
    }
    const [cmd, args] = ext === '.ps1' ? ['powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path]] : ['cmd.exe', ['/c', path]]
    return new Promise((resolve, reject) => execFile(cmd, args, { timeout: 60_000, env: { ...process.env, BIZOS_INPUT: input } },
      (e, out, err) => (e ? reject(new Error(String(err || e.message).trim().split('\n')[0])) : resolve(String(out)))))
  },
}
