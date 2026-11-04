import { keepPreviousData, QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import type { AgReportState } from 'ag-studio'
import { motion } from 'motion/react'
import { useState } from 'react'
import { Mark } from '../brand/Mark'
import { api, config } from '../lib/bridge'
import { Markdown } from '../lib/Markdown'
import { Actions } from './Actions'
import { applyLive, Studio } from './Studio'
import type { WorkspaceMeta, WorkspaceSpec } from './types'
import './workspace.css'

const client = new QueryClient({ defaultOptions: { queries: { retry: 2, refetchOnWindowFocus: false } } })
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
  const meta = useQuery({ queryKey: ['meta', id], queryFn: () => api<WorkspaceMeta>(`/workspaces/${id}/meta`), refetchInterval: 1200 })
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

  if (meta.error) return <Empty text={meta.error.message} />
  if (!meta.data || !cfg.data) return <Loading />
  const m = meta.data
  const widgets = Object.keys(spec.data?.state.pages[0]?.widgets ?? {}).length

  return (
    <div className="wsp">
      <header className="wsp-head">
        <div className="brand"><Mark size={26} tile /><span>BizOS</span></div>
        <span className="crumb">Workspace</span>
        {!m.complete && <span className="crumb-tag live-tag"><i className="live" />Agent editing</span>}
        <span className="grow" />
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

      <div className="wsp-grid">
        <main className="canvas">
          {spec.data && widgets > 0
            ? <Studio ws={spec.data} license={cfg.data.agLicense} mode={mode} onState={(s) => editing && saveState(id, s, shownVersion)} />
            : <Designing />}
        </main>
        <aside className="wsp-rail">
          <section className="rail-block brief">
            <h2 className="rail-title">Analyst brief {!m.complete && <i className="live" />}</h2>
            <div className="md" data-streaming={!m.complete}><Markdown text={m.narrative || '…'} /></div>
          </section>
          {m.actions.length > 0 && <Actions wsId={m.id} actions={m.actions} />}
          {m.risks.length > 0 && (
            <section className="rail-block">
              <h2 className="rail-title">Watch out</h2>
              <ul className="risks">{m.risks.map((r) => <li key={r}>{r}</li>)}</ul>
            </section>
          )}
        </aside>
      </div>
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
