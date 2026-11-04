/**
 * Overlay store: lives outside React, subscribes to the backend WebSocket and Electron IPC once at
 * startup, and is read with useSyncExternalStore (no useEffect anywhere).
 */
import { useSyncExternalStore } from 'react'
import { api, bizos, config } from '../lib/bridge'
import { FOLLOW_UP_MS, heardOutcome, initial, reduce, SILENCE_MS, spokenSummary, voiceDecision, type Caps, type Event, type State } from './state'

let state: State = initial
const subs = new Set<() => void>()
let socket: WebSocket | null = null

export function dispatch(e: Event) {
  state = reduce(state, e)
  subs.forEach((fn) => fn())
}

export const useOverlay = () =>
  useSyncExternalStore((fn) => (subs.add(fn), () => void subs.delete(fn)), () => state)

const send = (msg: object) => socket?.readyState === WebSocket.OPEN && socket.send(JSON.stringify(msg))

async function connect() {
  const { backendUrl, token } = await config
  socket = new WebSocket(`${backendUrl.replace(/^http/, 'ws')}/ws?token=${token}`)
  socket.onopen = () => dispatch({ type: 'online', online: true })
  socket.onclose = () => {
    dispatch({ type: 'online', online: false })
    setTimeout(connect, 1500)
  }
  socket.onmessage = async (m) => {
    const raw = JSON.parse(m.data)
    if (raw.type === 'client_call') { // the agent asks to open an app/link or read the screen; main does it
      const reply = await bizos.desktop(raw.op, raw.args)
      socket?.send(JSON.stringify({ type: 'client_result', id: raw.id, ...reply }))
      return
    }
    const e = raw as Event
    dispatch(e)
    if (e.type === 'workspace') bizos.openWorkspace(e.id)
    const handsFree = state.handsFree === 'on'
    // Hands-free means no clicks: run the plan. A step that can lose work (closing apps) needs a spoken "confirm".
    if (e.type === 'plan' && handsFree && !e.plan.confirm) actions.proceed()
    if (e.type === 'plan' && handsFree && e.plan.confirm && voiceTurn) {
      void voiceConfirm(`Before I go on: ${e.plan.confirm}. Say confirm, or cancel.`, (yes) => (yes ? actions.proceed() : actions.cancel()))
    }
    if (e.type === 'consent' && state.alwaysCapture) actions.consent(true, { auto: true }) // global "Always yes"
    else if (e.type === 'consent' && handsFree && voiceTurn) {
      void voiceConfirm(`To answer, I need a screenshot of ${e.target || 'your screen'}. Say yes, or no.`, (yes) => void actions.consent(yes))
    }
    if (e.type === 'done' && voiceTurn) void converse()
    if (e.type === 'error' && voiceTurn) {
      voiceTurn = false
      void say(e.message)
    }
  }
}

async function pollCaps(tries = 40) {
  try {
    const { capabilities } = await api<{ capabilities: Caps }>('/health')
    dispatch({ type: 'caps', caps: capabilities })
    if (capabilities.vision !== null) return
  } catch {
    /* backend still starting */
  }
  if (tries > 0) setTimeout(() => pollCaps(tries - 1), 1500)
}

async function pollChrome() {
  try {
    const x = await api<{ connected: boolean; token: string; outdated: boolean }>('/extension')
    dispatch({ type: 'chrome', connected: x.connected, token: x.token, outdated: x.outdated })
  } catch {
    /* backend still starting */
  }
}

export const actions = {
  summon: () => bizos.summon(),
  dismiss() {
    voiceTurn = false
    bizos.stopSpeaking()
    dispatch({ type: 'dismiss' })
    bizos.dismiss()
  },
  ask(goal: string, byVoice = false) {
    if (!goal.trim()) return
    voiceTurn = byVoice // typing takes over from a spoken conversation
    if (!byVoice) bizos.stopSpeaking()
    const fresh = state.fresh
    dispatch({ type: 'ask', goal })
    send({ type: 'ask', goal, context: state.context ?? {}, fresh })
  },
  proceed() {
    dispatch({ type: 'proceed' })
    send({ type: 'proceed' })
  },
  cancel() {
    dispatch({ type: 'cancel' })
    send({ type: 'cancel' })
  },
  async consent(allow: boolean, opts: { auto?: boolean; always?: boolean } = {}) {
    if (opts.always) actions.alwaysCapture(true)
    dispatch({ type: 'answerConsent', allow, auto: opts.auto })
    send({ type: 'consent', allow, image: allow ? await bizos.capture() : null })
  },
  alwaysCapture(on: boolean) {
    bizos.setAlwaysCapture(on)
    dispatch({ type: 'settings', alwaysCapture: on })
  },
  handsFree: (on: boolean) => bizos.setHandsFree(on), // main reports the listener's status back
  async dictate() {
    dispatch({ type: 'dictate' })
    document.querySelector<HTMLInputElement>('.ask input')?.focus()
    const error = await bizos.dictate()
    if (error) dispatch({ type: 'error', message: error })
  },
  mute() {
    if (!state.context?.app) return
    bizos.muteApp(state.context.app)
    dispatch({ type: 'summon', context: { app: state.context.app }, muted: true })
  },
  unmute: () => state.context?.app && bizos.muteApp(state.context.app, false), // main re-summons with the app's context
  openWorkspace: () => state.workspace && bizos.openWorkspace(state.workspace.id),
  fresh: () => dispatch({ type: 'fresh' }),
  async connectChrome() {
    const { url } = await api<{ url: string }>('/extension/pair', {})
    bizos.openInChrome(url)
  },
}

const setValue = (input: HTMLInputElement, v: string) =>
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, v)

/** Two soft rising tones: "speak now". Web Audio, so no sound file and the same on every OS. */
function chime() {
  try {
    const a = new AudioContext()
    ;[660, 990].forEach((hz, i) => {
      const o = a.createOscillator(), g = a.createGain(), t = a.currentTime + i * 0.11
      o.frequency.value = hz
      g.gain.setValueAtTime(0.0001, t)
      g.gain.exponentialRampToValueAtTime(0.12, t + 0.02)
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22)
      o.connect(g).connect(a.destination)
      o.start(t)
      o.stop(t + 0.25)
    })
    setTimeout(() => void a.close(), 600)
  } catch { /* no audio device: the "Speak now" prompt still shows */ }
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

// The request in progress came by voice: answer by voice, ask confirmations by voice, and keep the conversation going.
let voiceTurn = false

/**
 * Dictate into the ask field until the person pauses: resolves with what they said, or null after silence (or if
 * the panel was closed / they typed instead). The OS dictation never says when it's done, so a pause in typing is.
 */
async function listen(silenceMs = SILENCE_MS): Promise<string | null> {
  const input = document.querySelector<HTMLInputElement>('.ask input')
  if (!input || input.disabled) return null
  // macOS "start dictation" TOGGLES: if an earlier dictation is still on, it would switch it off. Handing focus
  // back first ends any dictation, so this always starts a fresh one.
  bizos.release()
  await wait(300)
  setValue(input, '') // never send leftovers from an earlier try
  document.querySelector('.panel')?.scrollTo({ top: 0, behavior: 'smooth' })
  await actions.dictate()
  if (!state.dictating) return null // dictation failed (error shown)
  await wait(300) // dictation needs a moment before it hears anything
  chime()
  return new Promise((resolve) => {
    const startedAt = Date.now()
    let last = '', changedAt = startedAt
    const timer = setInterval(() => {
      if (!state.dictating || !state.open) { clearInterval(timer); return resolve(null) } // sent by hand, or closed
      if (input.value !== last) [last, changedAt] = [input.value, Date.now()]
      const outcome = heardOutcome(input.value, startedAt, changedAt, Date.now(), silenceMs)
      if (outcome === 'wait') return
      clearInterval(timer)
      bizos.release() // ends the dictation, so it doesn't keep typing (or toggle off the next one)
      dispatch({ type: 'dictated' })
      resolve(outcome === 'send' ? input.value : null)
    }, 250)
  })
}

async function say(text: string) {
  dispatch({ type: 'speaking', on: true })
  await bizos.speak(text)
  dispatch({ type: 'speaking', on: false })
}

/** "Hey BizOS": take the request by voice. */
async function onWake() {
  bizos.stopSpeaking()
  if (state.muted) return
  if (state.pill === 'thinking' || state.pill === 'doing') return void say('Still working on your last request.')
  const text = await listen()
  if (text) {
    voiceTurn = true
    actions.ask(text, true)
  } else if (state.open && !state.dictating) {
    dispatch({ type: 'error', message: 'Didn’t hear anything. Say “Hey BizOS”, wait for the chime, then speak.' })
  }
}

/** A question that needs a yes or no (a step that can lose work, a screenshot): asked aloud, answered aloud. */
async function voiceConfirm(question: string, decide: (yes: boolean) => void) {
  await say(question)
  const text = await listen(FOLLOW_UP_MS)
  const input = document.querySelector<HTMLInputElement>('.ask input')
  if (input) setValue(input, '')
  const answer = text ? voiceDecision(text) : null
  if (answer) return decide(answer === 'yes')
  await say('I didn’t catch a clear yes or no, so I’ll wait for you to click.')
}

/** A hands-free run finished: say the answer, then listen for a follow-up without needing "Hey BizOS" again. */
async function converse() {
  await say(spokenSummary(state.brief || state.workspace?.headline || ''))
  if (!voiceTurn || state.handsFree !== 'on' || !state.open) return void (voiceTurn = false)
  const text = await listen(FOLLOW_UP_MS)
  if (text && voiceTurn) actions.ask(text, true)
  else voiceTurn = false // silence ends the conversation
}

let started = false
export function start() {
  if (started) return
  started = true
  connect()
  pollCaps()
  pollChrome()
  bizos.settings().then((x) => {
    dispatch({ type: 'settings', alwaysCapture: x.alwaysCapture })
    dispatch({ type: 'handsFree', status: x.handsFreeStatus ?? 'off' })
  })
  setInterval(pollChrome, 4000)
  bizos.onSummon((ctx) => dispatch({ type: 'summon', context: ctx, muted: ctx.off }))
  bizos.onHandsFree((status, error) => {
    dispatch({ type: 'handsFree', status })
    if (error) dispatch({ type: 'error', message: `Hands-free stopped: ${error}` })
  })
  // "Hey BizOS": main has already opened the panel; start dictation once the ask field is there.
  bizos.onWake(() => setTimeout(() => void onWake(), 250))
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape') actions.dismiss()
    // Enter approves a plan that is waiting, without parking focus (and a focus ring) on the button.
    const waiting = state.plan && state.pill === 'listening' && state.steps.every((x) => x.status === 'pending')
    if (e.key === 'Enter' && waiting && !(e.target instanceof HTMLInputElement)) actions.proceed()
  })
}
