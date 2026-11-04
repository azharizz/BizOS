/** Screen context read by the main process (L1 + L2). Every field is untrusted text. */
export interface Context {
  app?: string
  title?: string
  url?: string
  selection?: string
  clipboard?: string
  text?: string
}

export interface Config {
  backendUrl: string
  token: string
  agLicense: string
  platform: string
}

export interface Settings {
  muted: string[]
  alwaysCapture: boolean
  handsFree?: boolean
  handsFreeStatus?: 'off' | 'starting' | 'on' // read-only: the listener right now
}

/** What preload exposes to renderers as `window.bizos`. */
export interface Bridge {
  config: () => Promise<Config>
  onSummon: (fn: (ctx: Context & { off?: boolean }) => void) => void
  summon: () => void
  setInteractive: (on: boolean) => void
  dismiss: () => void
  /** Quit BizOS entirely. */
  quit: () => void
  /** Hand keyboard focus back to the user's app (ends an OS dictation). */
  release: () => void
  drag: (dx?: number, dy?: number) => void
  capture: () => Promise<string | null>
  openWorkspace: (id: string) => void
  muteApp: (app: string, off?: boolean) => void
  settings: () => Promise<Settings>
  setAlwaysCapture: (on: boolean) => void
  dictate: () => Promise<string | null>
  setHandsFree: (on: boolean) => void
  /** Read text aloud with the OS voice; resolves when it has finished (or was stopped). */
  speak: (text: string) => Promise<void>
  stopSpeaking: () => void
  /** Listener status ('starting' | 'on' | 'off'), with a message when it stopped on an error. */
  onHandsFree: (fn: (status: 'off' | 'starting' | 'on', error?: string) => void) => void
  onWake: (fn: () => void) => void
  /** "Hey BizOS, stop" was heard. */
  onStop: (fn: () => void) => void
  desktop: (op: string, args: Record<string, string>) => Promise<{ ok: boolean; result?: unknown; error?: string }>
  openExternal: (url: string) => void
  openInChrome: (url: string) => void
}
