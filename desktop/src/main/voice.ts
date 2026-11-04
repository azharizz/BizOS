/**
 * Push-to-talk with the OS's own speech engine, one adapter per platform (factory, like sense/).
 * The renderer focuses the ask field first; the OS then types the words into it.
 *   macOS    built-in Dictation via the standard `startDictation:` action (on-device, no extra permissions code)
 *   Windows  built-in voice typing (Win+H). UNTESTED.
 */
import { Menu } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
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

/**
 * Spoken answers with the OS's own voice (no model). The text is passed as an argument / env var, never as code.
 * Returns a stop function; the promise settles when speech ends or is stopped.
 *   macOS    `say`
 *   Windows  System.Speech via PowerShell. UNTESTED.
 */
export function createSpeaker(platform: string) {
  let current: ChildProcess | null = null
  const stop = () => { current?.kill(); current = null }
  const speak = (text: string) =>
    new Promise<void>((resolve) => {
      stop()
      const proc = platform === 'win32'
        ? spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
          'Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:BIZOS_SAY)'],
          { env: { ...process.env, BIZOS_SAY: text } })
        : spawn('say', ['--', text])
      current = proc
      proc.on('exit', () => resolve())
      proc.on('error', () => resolve())
    })
  return { speak, stop }
}

export function createVoice(platform: string): () => Promise<void> {
  return ADAPTERS[platform] ?? (async () => { throw new Error(`voice input is not supported on ${platform}`) })
}
