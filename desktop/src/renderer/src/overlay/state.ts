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
  confirm?: boolean // has a step that can lose work: always needs the Proceed click
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
  | { type: 'handsFree'; status: HandsFree }

export const initial: State = {
  pill: 'idle', open: false, context: null, muted: false, goal: '', plan: null, steps: [], current: -1,
  consent: null, workspace: null, brief: '', error: null, caps: {}, online: false, alwaysCapture: false, captured: null, fresh: false, chrome: { connected: false },
  dictating: false, handsFree: 'off',
}

export function reduce(s: State, e: Event): State {
  switch (e.type) {
    case 'summon':
      return { ...s, open: true, context: e.context, muted: !!e.muted, error: null, pill: s.pill === 'idle' ? 'listening' : s.pill }
    case 'dismiss':
      return { ...s, open: false, dictating: false, pill: s.pill === 'listening' ? 'idle' : s.pill }
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
export function heardOutcome(text: string, startedAt: number, changedAt: number, now: number): 'send' | 'wait' | 'nothing' {
  if (text.trim()) return now - changedAt >= PAUSE_MS ? 'send' : 'wait'
  return now - startedAt >= SILENCE_MS ? 'nothing' : 'wait'
}

/** The one step to show when the list is collapsed: the step in progress, else the last that finished. */
export function latestStep(s: State): State['steps'][number] | null {
  if (s.steps[s.current]?.status === 'running') return s.steps[s.current]
  return [...s.steps].reverse().find((x) => x.status !== 'pending') ?? null
}
