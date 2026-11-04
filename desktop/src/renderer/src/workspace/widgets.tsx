/**
 * BizOS's own AG Studio widgets: they sit on the canvas like any chart (drag, resize, pages, saved with the layout).
 *   bizos-plan     the investigation's plan graph, live (statuses, PayPal approvals waiting on a person)
 *   bizos-diagram  any Mermaid diagram the agent wrote (flowchart, gantt, timeline, sequence, mind map...)
 *   bizos-ideas    an ideas map: the problem in the middle, next moves around it; click one to ask BizOS
 *   bizos-summary  the written brief
 *   bizos-action   one PayPal action card (press-and-hold to approve)
 *   bizos-text     a Markdown block (AG Studio's text widget shows Markdown raw)
 * Their content lives in the workspace by widget id (meta.content), not in the AG format: AG Studio drops format keys
 * it doesn't know, and a layout saved from Edit layout must not erase it.
 */
import { QueryClientProvider } from '@tanstack/react-query'
import { ReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { AgWidgetParams } from 'ag-studio'
import { createWidgets, type AgWidgetDefinition } from 'ag-studio-react'
import mermaid from 'mermaid'
import { motion } from 'motion/react'
import { Suspense, use, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { bizos } from '../lib/bridge'
import { Markdown } from '../lib/Markdown'
import { fold, withActions } from '../plan/graph'
import { PlanGraph } from '../plan/PlanGraph'
import { ActionCard } from './Actions'
import { useLive } from './live'
import { client } from './query'

type Params = AgWidgetParams
/** This widget's content from the live workspace meta. */
const useContent = (p: Params) => (useLive()?.content?.[p.widgetId] ?? {}) as Record<string, unknown>
/** AG Studio waits for a widget to say it's showing something; a ref callback does that without an effect. */
const shown = (p: Params) => (el: HTMLElement | null) => void (el && p.widgetApi.setDisplayState('displayed'))

const titleOf = (p: Params) => (p.format as { title?: { text?: string } } | undefined)?.title?.text ?? ''

/**
 * Expand: AG Studio has no "maximise widget", so the graph, diagram and ideas widgets open their content in a
 * full-window popup (zoom and pan inside). Esc, the close button or a click outside closes it.
 */
function Expandable({ title, children }: { title: string; children: (big: boolean) => ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      {children(false)}
      <button className="bw-expand" onClick={() => setOpen(true)} title="Open large (zoom and pan inside)" aria-label={`Expand ${title}`}>
        <svg width="13" height="13" viewBox="0 0 16 16"><path d="M9.5 2.5h4v4M6.5 13.5h-4v-4M13.5 2.5 9 7M2.5 13.5 7 9" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      {/* No exit animation: the widget re-renders on every live poll, which kept an invisible popup over the page. */}
      {open && createPortal(
        <motion.div className="bw-pop" onClick={() => setOpen(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.18 }}>
          <motion.section className="bw-pop-card" role="dialog" aria-label={title} tabIndex={-1}
            ref={(el: HTMLElement | null) => el?.focus()} onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
            onClick={(e) => e.stopPropagation()}
            initial={{ scale: 0.96, y: 12 }} animate={{ scale: 1, y: 0 }} transition={{ type: 'spring', stiffness: 380, damping: 32 }}>
            <header><h2>{title}</h2><span className="fine">Scroll or pinch to zoom · drag to move · Esc to close</span>
              <button onClick={() => setOpen(false)} aria-label="Close">×</button></header>
            <div className="bw-pop-body">{children(true)}</div>
          </motion.section>
        </motion.div>,
        // Inside the app's own root (Workspace renders #bw-pop-root): portaled straight to <body>, real clicks and
        // keys never reached React from inside AG Studio's widget portals.
        document.getElementById('bw-pop-root') ?? document.body,
      )}
    </>
  )
}

function Plan(p: Params) {
  const live = useLive()
  const nodes = live?.plan?.nodes ?? []
  if (!nodes.length) return <div ref={shown(p)} className="bw bw-plan"><p className="bw-empty">The plan appears here when the agent starts working.</p></div>
  const all = withActions(nodes, live?.actions ?? [])
  return (
    <div ref={shown(p)} className="bw bw-plan">
      <Expandable title={titleOf(p) || 'Plan'}>
        {(big) => <PlanGraph nodes={big ? all : fold(all)} height="100%" interactive />}
      </Expandable>
    </div>
  )
}

mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral', fontFamily: 'Bricolage Grotesque Variable' })
const svgs = new Map<string, Promise<string>>()
let seq = 0
/** One render per diagram text; a parse error is shown instead of the diagram. */
const render = (text: string) => {
  if (!svgs.has(text)) svgs.set(text, mermaid.render(`bz-mmd-${++seq}`, text).then((r) => r.svg, (e: Error) => `!${e.message}`))
  return svgs.get(text)!
}

function Svg({ text, big = false }: { text: string; big?: boolean }) {
  const svg = use(render(text))
  const [zoom, setZoom] = useState(1)
  if (svg.startsWith('!')) return <pre className="bw-error">This diagram has an error: {svg.slice(1, 300)}</pre>
  const html = <div className="bw-svg" style={big ? { width: `${zoom * 100}%` } : undefined} dangerouslySetInnerHTML={{ __html: svg }} /> // mermaid "strict": sanitised SVG
  if (!big) return html
  return (
    <div className="bw-zoom" onWheel={(e) => (e.ctrlKey || e.metaKey) && setZoom((z) => Math.min(4, Math.max(0.5, z * (e.deltaY < 0 ? 1.1 : 0.9))))}>
      {html}
      <div className="bw-zoom-ctl">
        <button onClick={() => setZoom((z) => Math.max(0.5, z / 1.25))} aria-label="Zoom out">−</button>
        <button onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
        <button onClick={() => setZoom((z) => Math.min(4, z * 1.25))} aria-label="Zoom in">+</button>
      </div>
    </div>
  )
}

function Diagram(p: Params) {
  const text = String(useContent(p).source ?? '')
  return (
    <div ref={shown(p)} className="bw bw-diagram">
      {text ? (
        <Expandable title={titleOf(p) || 'Diagram'}>
          {(big) => <Suspense fallback={<p className="bw-empty">Drawing…</p>}><Svg text={text} big={big} /></Suspense>}
        </Expandable>
      ) : <p className="bw-empty">No diagram yet.</p>}
    </div>
  )
}

type Idea = { label: string; effort?: string; risk?: string; ask: string }
function Ideas(p: Params) {
  const s = useContent(p)
  const ideas = (s.ideas as Idea[] | undefined) ?? []
  const r = 220
  const nodes: Node[] = [
    { id: 'c', position: { x: -95, y: -28 }, data: { label: String(s.center ?? '') }, className: 'bw-idea-center', draggable: false },
    ...ideas.map((idea, i) => {
      const a = (2 * Math.PI * i) / ideas.length - Math.PI / 2
      return {
        id: String(i), position: { x: Math.cos(a) * r - 90, y: Math.sin(a) * r * 0.62 - 26 }, draggable: false,
        className: 'bw-idea', data: { label: <span title={`Ask BizOS: ${idea.ask}`}><b>{idea.label}</b><i>{[idea.effort && `${idea.effort} effort`, idea.risk].filter(Boolean).join(' · ')}</i></span> },
      }
    }),
  ]
  const edges: Edge[] = ideas.map((_, i) => ({ id: `e${i}`, source: 'c', target: String(i) }))
  return (
    <div ref={shown(p)} className="bw bw-ideas">
      <Expandable title={titleOf(p) || 'Ideas'}>
        {(big) => (
          <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.15 }} nodesConnectable={false}
            onInit={(rf) => setTimeout(() => void rf.fitView({ padding: 0.15 }), 200)}
            onNodeClick={(_, n) => n.id !== 'c' && bizos.askOverlay(ideas[Number(n.id)].ask)}
            panOnDrag={big} zoomOnScroll={big} zoomOnDoubleClick={false} proOptions={{ hideAttribution: true }} />
        )}
      </Expandable>
    </div>
  )
}

function Summary(p: Params) {
  const live = useLive()
  return (
    <div ref={shown(p)} className="bw bw-summary md" data-streaming={live ? !live.complete : false}>
      <Markdown text={live?.narrative || '…'} />
    </div>
  )
}

function Text(p: Params) {
  return <div ref={shown(p)} className="bw bw-text md"><Markdown text={String(useContent(p).text ?? '')} /></div>
}

function Action(p: Params) {
  const live = useLive()
  const a = live?.actions.find((x) => x.id === live.content?.[p.widgetId]?.actionId)
  return (
    <div ref={shown(p)} className="bw bw-action">
      {a && live ? <QueryClientProvider client={client}><ActionCard wsId={live.id} a={a} /></QueryClientProvider>
        : <p className="bw-empty">This action is no longer in the workspace.</p>}
    </div>
  )
}

const def = (id: string, label: string, comp: (p: Params) => React.ReactNode, description: string, size = { width: 640, height: 320 }): AgWidgetDefinition => ({
  id, label, comp, form: (f) => f.createDefaults({}), defaultSize: size, minSize: { width: 220, height: 140 },
  ai: { label, description },
})

export const BIZOS_WIDGETS = [
  def('bizos-plan', 'Plan graph', Plan, 'The live plan of the investigation as a graph'),
  def('bizos-diagram', 'Diagram', Diagram, 'A Mermaid diagram: flowchart, gantt, timeline, sequence, mind map, ER'),
  def('bizos-ideas', 'Ideas map', Ideas, 'Possible next moves around a problem; click one to ask BizOS'),
  def('bizos-summary', 'Summary', Summary, 'The analyst brief', { width: 380, height: 320 }),
  def('bizos-text', 'Text', Text, 'A Markdown text block', { width: 480, height: 200 }),
  def('bizos-action', 'PayPal action', Action, 'A PayPal action a person approves', { width: 380, height: 280 }),
]

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const widgets = (base: { menu: any[] }) => createWidgets<any>({
  additionalTypes: BIZOS_WIDGETS,
  menu: [...base.menu, { label: 'BizOS', widgetIds: BIZOS_WIDGETS.map((w) => w.id) }],
})
