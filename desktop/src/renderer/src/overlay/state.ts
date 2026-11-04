import type { Context } from '../../../shared/types'

export type Pill = 'idle' | 'listening' | 'thinking' | 'doing'
export type StepStatus = 'pending' | 'running' | 'verified' | 'failed'

export interface Plan {
  flow: string
  team: string
  title: string
  subject: string
  rationale: string
  steps: string[]
  sensed: string[]
  agentic?: boolean
  editing?: { id: string; title: string } | null // null: this plan starts a new workspace
  confirm?: string | null // a step that can lose work (its label): never auto-run, needs a click or a spoken "confirm"
}

export interface Caps { model?: string; tools?: boolean | null; vision?: boolean | null; error?: string | null }

export interface State {
  pill: Pill
  open: boolean
  context: Context | null
  muted: boolean
  goal: string
  plan: Plan | null
  steps: { index: number; label: string; status: StepStatus; note?: string }[]
  current: number
  consent: { reason: string; target?: string; model?: string } | null
  workspace: { id: string; title: string; headline: string } | null
  brief: string
  error: string | null
  caps: Caps
  online: boolean
  alwaysCapture: boolean
  captured: 'auto' | 'once' | null
  fresh: boolean
  chrome: { connected: boolean; token?: string; outdated?: boolean }
  dictating: boolean // the OS dictation was started from BizOS (it doesn't say when it stops)
  speaking: boolean // reading an answer or a question aloud
  handsFree: HandsFree
}

export type HandsFree = 'off' | 'starting' | 'on'

export type Event =
  | { type: 'summon'; context: Context; muted?: boolean }
  | { type: 'dismiss' }
  | { type: 'ask'; goal: string }
  | { type: 'proceed' }
  | { type: 'cancel' }
  | { type: 'answerConsent'; allow: boolean; auto?: boolean }
  | { type: 'settings'; alwaysCapture: boolean }
  | { type: 'caps'; caps: Caps }
  | { type: 'online'; online: boolean }
  | { type: 'chrome'; connected: boolean; token?: string; outdated?: boolean }
  // from the backend
  | { type: 'plan'; plan: Plan }
  | { type: 'consent'; reason: string; target?: string; model?: string }
  | { type: 'step'; index: number; label: string; status: StepStatus; note?: string }
  | { type: 'workspace'; id: string; title: string; headline: string }
  | { type: 'token'; text: string }
  | { type: 'brief_reset' }
  | { type: 'fresh' }
  | { type: 'done'; workspace_id: string }
  | { type: 'error'; message: string }
  | { type: 'dictate' }
  | { type: 'dictated' }
  | { type: 'speaking'; on: boolean }
  | { type: 'handsFree'; status: HandsFree }

export const initial: State = {
  pill: 'idle', open: false, context: null, muted: false, goal: '', plan: null, steps: [], current: -1,
  consent: null, workspace: null, brief: '', error: null, caps: {}, online: false, alwaysCapture: false, captured: null, fresh: false, chrome: { connected: false },
  dictating: false, speaking: false, handsFree: 'off',
}

export function reduce(s: State, e: Event): State {
  switch (e.type) {
    case 'summon':
      return { ...s, open: true, context: e.context, muted: !!e.muted, error: null, pill: s.pill === 'idle' ? 'listening' : s.pill }
    case 'dismiss':
      return { ...s, open: false, dictating: false, speaking: false, pill: s.pill === 'listening' ? 'idle' : s.pill }
    case 'ask':
      return { ...s, dictating: false, goal: e.goal, pill: 'thinking', plan: null, steps: [], current: -1, brief: '', error: null, consent: null, captured: null, fresh: false }
    case 'plan':
      return { ...s, plan: e.plan, pill: 'listening', steps: e.plan.steps.map((label, index) => ({ index, label, status: 'pending' })) }
    case 'consent':
      return { ...s, pill: 'listening', consent: { reason: e.reason, target: e.target, model: e.model } }
    case 'answerConsent':
      return { ...s, consent: null, pill: 'thinking', captured: e.allow ? (e.auto ? 'auto' : 'once') : null }
    case 'settings':
      return { ...s, alwaysCapture: e.alwaysCapture }
    case 'proceed':
      return { ...s, pill: 'doing', current: 0 }
    case 'cancel':
      return { ...s, pill: 'idle', plan: null, steps: [], consent: null }
    case 'step': {
      // The agent may add steps beyond the approved plan (extra queries, page reads): append those.
      const step = { index: e.index, label: e.label, status: e.status, note: e.note }
      const known = s.steps.some((st) => st.index === e.index)
      const steps = known ? s.steps.map((st) => (st.index === e.index ? step : st)) : [...s.steps, step]
      return { ...s, steps, current: steps.findIndex((st) => st.index === e.index) }
    }
    case 'workspace':
      return { ...s, workspace: { id: e.id, title: e.title, headline: e.headline } }
    case 'fresh':
      return { ...s, workspace: null, fresh: true }
    case 'brief_reset':
      return { ...s, brief: '' }
    case 'token':
      return { ...s, brief: s.brief + e.text }
    case 'done':
      return { ...s, pill: 'idle', current: -1 }
    case 'error':
      return { ...s, pill: 'idle', error: e.message, consent: null, dictating: false }
    case 'caps':
      return { ...s, caps: e.caps }
    case 'online':
      return { ...s, online: e.online }
    case 'dictate':
      return { ...s, dictating: true }
    case 'dictated':
      return { ...s, dictating: false }
    case 'speaking':
      return { ...s, speaking: e.on }
    case 'handsFree':
      return { ...s, handsFree: e.status }
    case 'chrome':
      return { ...s, chrome: { connected: e.connected, token: e.token, outdated: e.outdated } }
  }
}

/**
 * Hands-free: the OS dictation types into the ask field but never says when it's done. A pause in the typing
 * (PAUSE_MS) means the person finished; nothing at all for SILENCE_MS means they didn't say anything.
 */
export const PAUSE_MS = 2000
export const SILENCE_MS = 10_000
export const FOLLOW_UP_MS = 8000 // conversation mode: listening again after an answer; silence just ends it
export function heardOutcome(text: string, startedAt: number, changedAt: number, now: number, silenceMs = SILENCE_MS): 'send' | 'wait' | 'nothing' {
  if (text.trim()) return now - changedAt >= PAUSE_MS ? 'send' : 'wait'
  return now - startedAt >= silenceMs ? 'nothing' : 'wait'
}

const YES = /\b(yes|yeah|yep|confirm(ed)?|proceed|go ahead|do it|okay|ok)\b/i
const NO = /\b(no|nope|cancel|stop|don'?t|abort)\b/i
/** A spoken answer to "confirm or cancel?": only an unambiguous one counts; anything mixed or unclear is null. */
export function voiceDecision(text: string): 'yes' | 'no' | null {
  const yes = YES.test(text), no = NO.test(text)
  return yes === no ? null : yes ? 'yes' : 'no'
}

/** What gets read aloud when a hands-free run finishes: the brief's bold headline (or first sentence), short. */
export function spokenSummary(brief: string): string {
  const bold = brief.match(/\*\*(.+?)\*\*/s)?.[1]
  const text = (bold ?? brief.split(/(?<=[.!?])\s/)[0] ?? '').replace(/[*_`#>[\]]/g, '').replace(/\s+/g, ' ').trim()
  return text ? (text.length > 260 ? text.slice(0, 257).replace(/\s+\S*$/, '') + '…' : text) : 'Done.'
}

/** The one step to show when the list is collapsed: the step in progress, else the last that finished. */
export function latestStep(s: State): State['steps'][number] | null {
  if (s.steps[s.current]?.status === 'running') return s.steps[s.current]
  return [...s.steps].reverse().find((x) => x.status !== 'pending') ?? null
}
