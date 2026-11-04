/**
 * Push-to-talk with the OS's own speech engine, one adapter per platform (factory, like sense/).
 * The renderer focuses the ask field first; the OS then types the words into it.
 *   macOS    built-in Dictation via the standard `startDictation:` action (on-device, no extra permissions code)
 *   Windows  built-in voice typing (Win+H). UNTESTED.
 */
import { Menu } from 'electron'
import { run } from './sense/run'

const WIN_H = `Add-Type @"
using System; using System.Runtime.InteropServices;
public class K { [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e); }
"@
[K]::keybd_event(0x5B,0,0,[UIntPtr]::Zero); [K]::keybd_event(0x48,0,0,[UIntPtr]::Zero)
[K]::keybd_event(0x48,0,2,[UIntPtr]::Zero); [K]::keybd_event(0x5B,0,2,[UIntPtr]::Zero)`

const ADAPTERS: Record<string, () => Promise<void>> = {
  darwin: async () => Menu.sendActionToFirstResponder('startDictation:'),
  win32: async () => void (await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', WIN_H])),
}

export function createVoice(platform: string): () => Promise<void> {
  return ADAPTERS[platform] ?? (async () => { throw new Error(`voice input is not supported on ${platform}`) })
}
