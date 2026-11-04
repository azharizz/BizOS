import { keepPreviousData, QueryClientProvider, useQuery } from '@tanstack/react-query'
import type { AgReportState } from 'ag-studio'
import { motion } from 'motion/react'
import { useState } from 'react'
import { Mark } from '../brand/Mark'
import { api, config } from '../lib/bridge'
import { Markdown } from '../lib/Markdown'
import { Actions } from './Actions'
import { setLive } from './live'
import { client } from './query'
import { applyLive, showPage, Studio } from './Studio'
import type { WorkspaceMeta, WorkspaceSpec } from './types'
import './workspace.css'

const ease = [0.22, 1, 0.36, 1] as const

let saveTimer: ReturnType<typeof setTimeout> | undefined
let editing = false // read at call time: AG Studio may keep the first callback it was given
let shownVersion = 0 // agent_version of the canvas currently on screen
/** The user's own layout edits go back to the server, so the agent's next edit builds on them. */
// Only saved while the user is in "Edit layout": a window that is just showing the canvas never writes back.
// base_version = the agent version this canvas was rendered from; the server refuses saves made from an older one
// (otherwise a window that hasn't caught up yet would erase the agent's newest widgets).
const saveState = (id: string, state: AgReportState, version: number) => {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => api(`/workspaces/${id}/state`, { state, base_version: version }, 'PUT').catch(() => {}), 700)
}

export default function Workspace({ id }: { id: string }) {
  return <QueryClientProvider client={client}><View id={id} /></QueryClientProvider>
}

function View({ id }: { id: string }) {
  // Cheap poll; the canvas itself is refetched only when the agent changes it (agent_version).
  const meta = useQuery({
    queryKey: ['meta', id], refetchInterval: 1200,
    queryFn: async () => {
      const m = await api<WorkspaceMeta>(`/workspaces/${id}/meta`)
      setLive(m) // BizOS widgets on the canvas (plan, brief, actions) read it
      return m
    },
  })
  const version = meta.data?.agent_version
  const spec = useQuery({
    queryKey: ['canvas', id, version],
    queryFn: async () => {
      const ws = await api<WorkspaceSpec>(`/workspaces/${id}`)
      applyLive(ws) // widgets/layout edits land in place; new data sources remount (keyed by signature)
      shownVersion = ws.agent_version
      return ws
    },
    enabled: version !== undefined,
    placeholderData: keepPreviousData,
  })
  const cfg = useQuery({ queryKey: ['config'], queryFn: () => config, staleTime: Infinity })
  const [mode, setMode] = useState<'view' | 'edit'>('view')
  const [page, setPage] = useState('')

  if (meta.error) return <Empty text={meta.error.message} />
  if (!meta.data || !cfg.data) return <Loading />
  const m = meta.data
  const widgets = (spec.data?.state.pages ?? []).reduce((n, p) => n + Object.keys(p.widgets ?? {}).length, 0)
  const current = page || spec.data?.state.selectedPageId || m.pages[0]?.id
  // The brief and actions live in the side rail, unless the agent (or you) put them on the canvas.
  const onCanvas = (type: string) => (spec.data?.state.pages ?? []).flatMap((p) => Object.entries(p.widgets ?? {}))
    .filter(([, w]) => (w as { type?: string } | undefined)?.type === type).map(([id]) => id)
  const briefOnCanvas = onCanvas('bizos-summary').length > 0
  const placed = new Set(onCanvas('bizos-action').map((id) => m.content?.[id]?.actionId))
  const railActions = m.actions.filter((a) => !placed.has(a.id))

  return (
    <div className="wsp">
      <header className="wsp-head">
        <div className="brand"><Mark size={26} tile /><span>BizOS</span></div>
        <span className="crumb">Workspace</span>
        {!m.complete && <span className="crumb-tag live-tag"><i className="live" />Agent editing</span>}
        <span className="grow" />
        <History current={id} />
        <div className="seg" role="radiogroup" aria-label="Canvas mode">
          {(['view', 'edit'] as const).map((x) => (
            <button key={x} role="radio" aria-checked={mode === x} onClick={() => { editing = x === 'edit'; setMode(x) }}>
              {mode === x && <motion.span layoutId="seg-hl" className="seg-hl" transition={{ type: 'spring', stiffness: 500, damping: 36 }} />}
              <span>{x === 'view' ? 'Explore' : 'Edit layout'}</span>
            </button>
          ))}
        </div>
      </header>

      <section className="hero">
        <Title key={m.title} text={m.title || 'New workspace'} />
        {m.headline && (
          <motion.p key={m.headline} className="headline" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease }}>
            {m.headline}
          </motion.p>
        )}
        <p className="meta">
          {m.runs.length} {m.runs.length === 1 ? 'investigation' : 'investigations'} · {widgets} widgets · {m.sources.filter((s) => !s.startsWith('kpi_')).length} data sources
        </p>
      </section>

      {m.pages.length > 1 && (
        <nav className="pages" role="tablist" aria-label="Pages">
          {m.pages.map((p) => (
            <button key={p.id} role="tab" aria-selected={current === p.id} onClick={() => { setPage(p.id); showPage(p.id) }}>
              {current === p.id && <motion.span layoutId="page-hl" className="page-hl" transition={{ type: 'spring', stiffness: 500, damping: 36 }} />}
              <span>{p.title}</span>
            </button>
          ))}
        </nav>
      )}

      <div className="wsp-grid" data-rail={!briefOnCanvas || railActions.length > 0 || m.risks.length > 0}>
        <main className="canvas">
          {spec.data && widgets > 0
            ? <Studio ws={spec.data} license={cfg.data.agLicense} mode={mode} onState={(s) => editing && saveState(id, s, shownVersion)} />
            : <Designing />}
        </main>
        <aside className="wsp-rail">
          {!briefOnCanvas && (
            <section className="rail-block brief">
              <h2 className="rail-title">Analyst brief {!m.complete && <i className="live" />}</h2>
              <div className="md" data-streaming={!m.complete}><Markdown text={m.narrative || '…'} /></div>
            </section>
          )}
          {railActions.length > 0 && <Actions wsId={m.id} actions={railActions} />}
          {m.risks.length > 0 && (
            <section className="rail-block">
              <h2 className="rail-title">Watch out</h2>
              <ul className="risks">{m.risks.map((r) => <li key={r}>{r}</li>)}</ul>
            </section>
          )}
        </aside>
      </div>
      <div id="bw-pop-root" /> {/* host for widget popups (Expand), inside the app's React root */}
    </div>
  )
}

type Past = { id: string; title: string; headline: string; updated: number }
const ago = (t: number) => {
  const m = Math.round((Date.now() / 1000 - t) / 60)
  return m < 60 ? `${Math.max(m, 1)}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`
}

/** Every workspace is kept (local memory): reopen or search old ones. Opening one switches this window to it. */
function History({ current }: { current: string }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const list = useQuery({
    queryKey: ['history', q], enabled: open, placeholderData: keepPreviousData,
    queryFn: () => api<Past[]>(`/workspaces${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`),
  })
  return (
    <div className="history">
      <button className="history-btn" aria-expanded={open} onClick={() => setOpen(!open)}>History</button>
      {open && (
        <motion.div className="history-pop" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease }}>
          <input autoFocus placeholder="Search past workspaces…" value={q} onChange={(e) => setQ(e.target.value)} />
          <ul>
            {(list.data ?? []).map((w) => (
              <li key={w.id}>
                <button disabled={w.id === current} onClick={() => { location.hash = `/w/${w.id}` }}>
                  <b>{w.title || 'Untitled'}</b>
                  <span>{w.headline || ' '}</span>
                  <i>{w.id === current ? 'open' : ago(w.updated)}</i>
                </button>
              </li>
            ))}
            {list.data?.length === 0 && <li className="history-empty">Nothing found.</li>}
          </ul>
        </motion.div>
      )}
    </div>
  )
}

function Title({ text }: { text: string }) {
  return (
    <h1 className="title" aria-label={text}>
      {text.split(' ').map((word, i) => (
        <span key={i} className="word" aria-hidden>
          <motion.span initial={{ y: '105%' }} animate={{ y: 0 }} transition={{ delay: 0.05 + i * 0.045, duration: 0.75, ease }}>{word}</motion.span>
        </span>
      ))}
    </h1>
  )
}

function Designing() {
  return (
    <div className="designing">
      <div className="ghost-grid">
        {[3, 3, 3, 3, 6, 6, 12].map((span, i) => (
          <motion.i key={i} style={{ gridColumn: `span ${span}` }} initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08, duration: 0.5, ease }} />
        ))}
      </div>
      <p>The agent is designing this workspace…</p>
    </div>
  )
}

function Loading() {
  return (
    <div className="wsp-center">
      <Mark size={44} tile live />
      <p>Opening workspace…</p>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return (
    <div className="wsp-center">
      <Mark size={44} tile />
      <p>This workspace is gone ({text}). Workspaces live until the engine restarts. Ask again from the overlay.</p>
    </div>
  )
}
