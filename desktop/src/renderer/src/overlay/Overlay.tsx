import { AnimatePresence, motion, type Transition } from 'motion/react'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { Mark } from '../brand/Mark'
import { bizos } from '../lib/bridge'
import { Markdown } from '../lib/Markdown'
import { latestStep, type State } from './state'
import { actions, start, useOverlay } from './store'
import './overlay.css'

start()

const spring: Transition = { type: 'spring', stiffness: 520, damping: 38, mass: 0.8 }
const soft: Transition = { type: 'spring', stiffness: 260, damping: 30 }
const focusOnMount = (el: HTMLElement | null) => el?.focus()
let grab = [0, 0] // pointer position (screen) when the grip was pressed
const host = (url?: string) => { try { return url ? new URL(url).host : '' } catch { return '' } }

export default function Overlay() {
  const s = useOverlay()
  return (
    // Outside the pill and panel, clicks fall through to the user's app.
    <div className="ov" onPointerEnter={() => bizos.setInteractive(true)} onPointerLeave={() => bizos.setInteractive(false)}>
      <Pill s={s} />
      <AnimatePresence>{s.open && <Panel key="panel" s={s} />}</AnimatePresence>
    </div>
  )
}

function Pill({ s }: { s: State }) {
  const step = s.steps[s.current]
  const label = {
    idle: s.online ? 'BizOS' : 'Connecting',
    listening: s.dictating ? 'Listening' : 'Ready', // the mic is only live while dictating
    thinking: 'Thinking',
    doing: step ? `${s.current + 1}/${s.steps.length} · ${step.label}` : 'Doing',
  }[s.pill]
  const busy = s.pill === 'thinking' || s.pill === 'doing'
  const shown = busy ? label : s.speaking ? 'Speaking' : s.dictating ? 'Listening' : label // conversation mode
  const done = s.steps.filter((x) => x.status === 'verified').length
  return (
    <motion.div layout transition={spring} className="pill" data-state={s.pill} data-online={s.online} data-mic={s.dictating}
      style={{ '--p': done / Math.max(s.steps.length, 1) } as CSSProperties}>
      <span className="pill-grip" title="Drag to move" aria-hidden
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); grab = [e.screenX, e.screenY]; bizos.drag() }}
        onPointerMove={(e) => e.currentTarget.hasPointerCapture(e.pointerId) && bizos.drag(e.screenX - grab[0], e.screenY - grab[1])} />
      <button className="pill-main" onClick={() => (s.open ? actions.dismiss() : actions.summon())}
        aria-label={s.open ? 'Close BizOS' : 'Open BizOS'} aria-live="polite">
        <motion.span layout="position" className="pill-mark"><Mark size={18} live={s.pill === 'idle' && s.online} /></motion.span>
        <span className="pill-label">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span key={shown} initial={{ y: 12, opacity: 0, filter: 'blur(4px)' }} animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
              exit={{ y: -12, opacity: 0, filter: 'blur(4px)' }} transition={spring}>{shown}</motion.span>
          </AnimatePresence>
        </span>
        <span className="ind" aria-hidden><i /><i /><i /></span>
        {s.pill === 'idle' && !s.speaking && <kbd className="pill-kbd">{s.handsFree === 'on' ? '“Hey BizOS”' : '⌘⇧␣'}</kbd>}
      </button>
      {(busy || s.speaking) && (
        <button className="pill-stop" onClick={actions.stop} aria-label="Stop" title="Stop (Esc, or say “Hey BizOS, stop”)"><i /></button>
      )}
    </motion.div>
  )
}

function Panel({ s }: { s: State }) {
  return (
    <motion.section className="panel" role="dialog" aria-label="BizOS"
      initial={{ opacity: 0, y: -18, scale: 0.94, filter: 'blur(8px)' }}
      animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
      exit={{ opacity: 0, y: -12, scale: 0.97, filter: 'blur(6px)', transition: { duration: 0.16 } }}
      transition={soft} style={{ transformOrigin: 'top center' }}>
      <ContextStrip s={s} />
      {s.muted ? (
        <p className="muted-note">BizOS is off for <b>{s.context?.app}</b>. Nothing from this app is read. <button className="linkish" onClick={actions.unmute}>Turn back on</button></p>
      ) : (
        <>
          <Ask s={s} />
          <AnimatePresence mode="popLayout" initial={false}>
            {s.error && <motion.p key="err" className="note-error" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>{s.error}</motion.p>}
            {s.consent && <Consent key="consent" s={s} />}
            {s.question && <Question key="question" text={s.question} />}
            {s.pill === 'thinking' && !s.plan && <Thinking key="thinking" />}
            {s.plan && <PlanCard key="plan" s={s} />}
          </AnimatePresence>
          {(s.brief || s.workspace) && <Brief s={s} />}
        </>
      )}
      <footer className="panel-foot">
        <span className="dot" data-on={s.online} /> {s.online ? 'Connected' : 'Starting engine…'}
        <span className="grow" />
        <HandsFree s={s} />
        <ChromeLink s={s} />
        <button className="chrome-link quit" onClick={() => bizos.quit()} title="Quit BizOS (stops the engine and the mic)">Quit</button>
      </footer>
    </motion.section>
  )
}

function HandsFree({ s }: { s: State }) {
  const on = s.handsFree !== 'off'
  return (
    <button className="chrome-link" data-on={s.handsFree === 'on'} aria-pressed={on} onClick={() => actions.handsFree(!on)}
      title={on ? 'Listening for “Hey BizOS” on this Mac (offline). Click to turn off.' : 'Say “Hey BizOS” to open BizOS and start dictating, even when it is closed. Speech is checked offline on this Mac.'}>
      <span className="dot" data-on={s.handsFree === 'on'} />{s.handsFree === 'starting' ? 'Starting mic…' : on ? 'Hands-free on' : 'Hands-free'}
    </button>
  )
}

function ChromeLink({ s }: { s: State }) {
  const { connected, outdated } = s.chrome
  const label = outdated ? 'Reload extension' : connected ? 'Chrome connected' : 'Connect Chrome'
  return (
    <button className="chrome-link" data-on={connected && !outdated} data-warn={outdated || undefined}
      onClick={() => !connected && actions.connectChrome()}
      title={outdated ? 'Chrome runs an old BizOS extension: click its reload icon in chrome://extensions'
        : connected ? 'Extension connected: pages are read from the DOM' : 'One click: opens a pairing page in Chrome'}>
      <span className="dot" data-on={s.chrome.connected} />{label}
    </button>
  )
}

function ContextStrip({ s }: { s: State }) {
  const c = s.context ?? {}
  const tiers = [
    ['L1', !!(c.app || c.title || c.url), 'App, window, URL, selection'],
    ['L2', !!(c.text || c.selection), 'On-screen text (Accessibility)'],
    ['L3', s.caps.vision === true, s.caps.vision === false ? s.caps.error ?? 'Model has no image input' : 'Screenshot, only with your consent'],
  ] as const
  return (
    <div className="ctx">
      <div className="ctx-where">
        <span className="ctx-app">{c.app ?? 'Nothing sensed yet'}</span>
        <span className="ctx-title">{c.title || host(c.url) || 'Press ⌘⇧Space over any app'}</span>
      </div>
      <div className="ctx-tiers">
        {tiers.map(([t, on, tip]) => t === 'L3' && s.alwaysCapture
          ? <button key={t} className="tier" data-on={on} data-auto onClick={() => actions.alwaysCapture(false)} title="Always yes is on: screens are captured without asking. Click to turn off.">L3 auto</button>
          : <span key={t} className="tier" data-on={on} title={tip}>{t}</span>)}
        {c.app && !s.muted && <button className="ctx-mute" onClick={actions.mute} title={`BizOS will stop reading ${c.app} until you turn it back on`}>Ignore this app</button>}
      </div>
    </div>
  )
}

function Ask({ s }: { s: State }) {
  const busy = s.pill === 'thinking' || s.pill === 'doing'
  const editing = s.plan && s.plan.editing !== undefined ? s.plan.editing : s.workspace // a new topic: no "Editing"
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    actions.ask(String(new FormData(e.currentTarget).get('goal') ?? ''))
  }
  return (
    <form className="ask" onSubmit={submit}>
      {editing && !busy && (
        <div className="editing">
          <span>Editing</span><b>{editing.title}</b>
          <button type="button" onClick={actions.fresh} title="Start a new workspace instead of editing this one">New</button>
        </div>
      )}
      <input ref={focusOnMount} name="goal" autoComplete="off" spellCheck={false} disabled={busy}
        placeholder={s.dictating ? 'Speak now…' : "Ask about what's on screen…"} aria-label="What should BizOS investigate?" />
      <button className="ask-go" disabled={busy} aria-label="Investigate">
        <svg width="16" height="16" viewBox="0 0 16 16"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      <button type="button" className="ask-mic" disabled={busy} onClick={actions.dictate} aria-label="Speak (built-in dictation)"
        title={navigator.platform.startsWith('Win') ? 'Voice typing (Win+H)' : 'Dictation (macOS)'}>
        <svg width="16" height="16" viewBox="0 0 16 16"><rect x="5.5" y="1.5" width="5" height="8" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.6" /><path d="M3 7.5a5 5 0 0 0 10 0M8 12.5v2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      </button>
    </form>
  )
}

function Thinking() {
  return (
    <motion.div className="thinking" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      {[0, 1, 2].map((i) => <span key={i} className="bar" style={{ animationDelay: `${i * 0.12}s` }} />)}
      <em>Reading context, choosing the right investigation…</em>
    </motion.div>
  )
}

/** The agent is about to do something that sends, submits, buys or deletes: it waits for this answer. */
function Question({ text }: { text: string }) {
  return (
    <motion.div className="card consent" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={soft}>
      <h3>Go ahead?</h3>
      <p>{text}</p>
      <div className="row">
        <button className="btn ghost" onClick={() => actions.answer(false)}>No</button>
        <span className="grow" />
        <button className="btn" onClick={() => actions.answer(true)}>Yes, do it</button>
      </div>
    </motion.div>
  )
}

function Consent({ s }: { s: State }) {
  const c = s.consent!
  return (
    <motion.div className="card consent" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={soft}>
      <h3>Look at your screen?</h3>
      <p>{c.reason}</p>
      <p className="fine">One screenshot of <b>{c.target ?? 'your screen'}</b>, sent once to <b>{c.model}</b>. Not stored.</p>
      <div className="row">
        <button className="btn ghost" onClick={() => actions.consent(false)}>No</button>
        <span className="grow" />
        <button className="btn ghost" onClick={() => actions.consent(true, { always: true })} title="Capture without asking again, for every app and site. Turn off from the L3 badge.">Always yes</button>
        <button className="btn" onClick={() => actions.consent(true)}>Yes, once</button>
      </div>
    </motion.div>
  )
}

function PlanCard({ s }: { s: State }) {
  const p = s.plan!
  const awaiting = s.pill === 'listening' && s.steps.every((x) => x.status === 'pending')
  return (
    <motion.div className="card plan" layout initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={soft}>
      <div className="plan-head">
        <span className="tag">{p.team}</span>
        {s.workspace && <span className="tag edit">Edits workspace</span>}
        {p.agentic && <span className="tag agent">Agent plan</span>}
        <span className="plan-subject">{p.subject}</span>
      </div>
      <h3>{p.title}</h3>
      <p className="plan-why">{p.rationale}</p>
      {s.captured && (
        <p className="captured">
          Screen captured {s.captured === 'auto' ? 'automatically (Always yes)' : 'once, with your consent'} and read by {s.caps.model ?? 'the model'}.
          {s.captured === 'auto' && <button className="linkish" onClick={() => actions.alwaysCapture(false)}>Turn off</button>}
        </p>
      )}
      {awaiting ? <AllSteps steps={s.steps} /> : <StepTicker s={s} />}
      <AnimatePresence>
        {awaiting && (
          <motion.div className="row plan-actions" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            <span className="fine">Reads: {p.sensed.join(', ') || 'nothing'} + company data</span>
            <span className="grow" />
            <button className="btn ghost" onClick={actions.cancel}>Cancel</button>
            <button className="btn" onClick={actions.proceed}>Proceed <kbd>↵</kbd></button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

type Steps = State['steps']

function StepRow({ st, n }: { st: Steps[number]; n: number }) {
  return (
    <>
      <StepIcon n={n} status={st.status} />
      <span className="step-label">{st.label}</span>
      {st.note && <span className="step-note">{st.note}</span>}
    </>
  )
}

function AllSteps({ steps }: { steps: Steps }) {
  return (
    <motion.ol className="steps" initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: 0.045 } } }}>
      {steps.map((st, i) => (
        <motion.li key={st.index} className="step" data-status={st.status}
          variants={{ hidden: { opacity: 0, x: -8, filter: 'blur(3px)' }, show: { opacity: 1, x: 0, filter: 'blur(0px)' } }}>
          <StepRow st={st} n={i + 1} />
        </motion.li>
      ))}
    </motion.ol>
  )
}

/** While the agent works: only the latest step, sliding up like a ticker; the rest one click away. */
function StepTicker({ s }: { s: State }) {
  const [open, setOpen] = useState(false)
  const latest = latestStep(s)
  const done = s.steps.filter((x) => x.status === 'verified' || x.status === 'failed').length
  const failed = s.steps.filter((x) => x.status === 'failed').length
  const n = latest ? s.steps.indexOf(latest) + 1 : 0
  return (
    <div className="ticker">
      <div className="ticker-head">
        <span className="ticker-count">{done}/{s.steps.length} steps{failed > 0 && ` · ${failed} failed`}</span>
        <span className="ticker-bar"><motion.i animate={{ scaleX: done / Math.max(s.steps.length, 1) }} transition={soft} /></span>
        <button className="linkish" onClick={() => setOpen(!open)}>{open ? 'Hide steps' : `Show all ${s.steps.length}`}</button>
      </div>
      <AnimatePresence initial={false} mode="popLayout">
        {open ? (
          <motion.div key="all" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={soft}>
            <AllSteps steps={s.steps} />
          </motion.div>
        ) : latest && (
          <motion.div key={`${latest.index}-${latest.status}`} className="step ticker-step" data-status={latest.status}
            initial={{ opacity: 0, y: 14, filter: 'blur(3px)' }} animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -14, filter: 'blur(3px)' }} transition={soft}>
            <StepRow st={latest} n={n} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function StepIcon({ n, status }: { n: number; status: string }) {
  return (
    <span className="step-icon" aria-label={status}>
      {status === 'verified' ? (
        <svg viewBox="0 0 16 16"><motion.path d="M3.5 8.5 6.5 11.5 12.5 4.5" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.35, ease: 'easeOut' }} /></svg>
      ) : status === 'failed' ? '×' : status === 'running' ? <i className="spin" /> : n}
    </span>
  )
}

function Brief({ s }: { s: State }) {
  const streaming = s.pill === 'doing' || (!!s.workspace && !s.brief)
  const working = s.pill === 'doing' || s.pill === 'thinking' // agent running or editing
  return (
    <motion.div className="card brief" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={soft}>
      {s.workspace && <h3>{s.workspace.title}</h3>}
      <div className="md" data-streaming={streaming}>
        <Markdown text={s.brief || s.workspace?.headline || ''} />
      </div>
      {s.workspace && (
        <button className="btn open-ws" data-busy={working} onClick={actions.openWorkspace} aria-busy={working}
          title={working ? 'The agent is still editing; you can watch it live' : undefined}>
          {working ? <><i className="spin dark" />Updating workspace…</> : <>Open workspace
            <svg width="14" height="14" viewBox="0 0 16 16"><path d="M5 11 11 5M6 5h5v5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg></>}
        </button>
      )}
    </motion.div>
  )
}
