// UNTESTED: built alongside macOS, never run on Windows. Uses user32 + UI Automation.
import type { Context } from '../../shared/types'
import { clean, run } from './run'

const SCRIPT = `
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class W {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
}
"@
Add-Type -AssemblyName UIAutomationClient
$h = [W]::GetForegroundWindow(); $sb = New-Object Text.StringBuilder 512; [void][W]::GetWindowText($h, $sb, 512)
$id = 0; [void][W]::GetWindowThreadProcessId($h, [ref]$id); $p = Get-Process -Id $id
$url = ""; $text = ""
try {
  $root = [Windows.Automation.AutomationElement]::FromHandle($h)
  if ($p.ProcessName -match 'chrome|msedge|brave|firefox') {
    $edit = $root.FindFirst([Windows.Automation.TreeScope]::Descendants,
      (New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::ControlTypeProperty, [Windows.Automation.ControlType]::Edit)))
    if ($edit) { $url = $edit.GetCurrentPropertyValue([Windows.Automation.ValuePattern]::ValueProperty) }
  }
  $text = [Windows.Automation.AutomationElement]::FocusedElement.Current.Name
} catch {}
@{ app = $p.ProcessName; title = $sb.ToString(); url = $url; text = $text } | ConvertTo-Json -Compress`

export function parseWin(stdout: string, clipboard: string): Context {
  try {
    const { app, title, url, text } = JSON.parse(stdout)
    return clean({ app, title, url, text, clipboard })
  } catch {
    return {}
  }
}

export async function readWin(clipboard: string): Promise<Context> {
  return parseWin(await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', SCRIPT], 4000), clipboard)
}
