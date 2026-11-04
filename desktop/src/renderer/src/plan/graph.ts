/** The plan as a graph (from the backend's plan_graph): pure layout, drawn by PlanGraph in the overlay and the workspace. */
export type Risk = 'read' | 'act' | 'risky' | 'money'
export type NodeStatus = 'pending' | 'running' | 'verified' | 'failed' | 'approval'

export interface PlanNode {
  index: number
  tool: string
  label: string
  risk: Risk | string
  after: number[]
  when: string
  core: boolean
  skipped: boolean
  status: NodeStatus | string
  note?: string
}

export const COL = 230
export const ROW = 92

/** Rows by longest path from the start (a step sits one row below everything it waits for), siblings side by side. */
export function layout(nodes: PlanNode[]) {
  const known = new Set(nodes.map((n) => n.index))
  const depth = new Map<number, number>()
  for (const n of nodes) depth.set(n.index, Math.max(0, ...n.after.filter((a) => known.has(a)).map((a) => (depth.get(a) ?? 0) + 1)))
  const rows = new Map<number, number[]>()
  for (const n of nodes) rows.set(depth.get(n.index)!, [...(rows.get(depth.get(n.index)!) ?? []), n.index])
  const positions: Record<number, { x: number; y: number }> = {}
  for (const [d, ids] of rows) ids.forEach((id, i) => (positions[id] = { x: (i - (ids.length - 1) / 2) * COL, y: d * ROW }))
  const edges = nodes.flatMap((n) => n.after.filter((a) => known.has(a)).map((a) => ({
    id: `${a}-${n.index}`, source: String(a), target: String(n.index), ...(n.when ? { label: n.when } : {}),
  })))
  return { positions, edges }
}

export interface ActionLink { id: string; step?: number | null; status?: string }

/** A PayPal proposal is "done" for the agent, but waits on a person: show that, then the real outcome. */
export function withActions(nodes: PlanNode[], actions: ActionLink[]): PlanNode[] {
  return nodes.map((n) => {
    const a = actions.find((x) => x.step === n.index)
    if (!a) return n
    const done = a.status === 'executed' || a.status === 'previewed-only'
    return { ...n, status: done ? 'verified' : a.status === 'failed' ? 'failed' : 'approval',
      note: done ? 'approved' : a.status === 'failed' ? 'PayPal refused it' : 'waiting for your approval' }
  })
}

/** The agent's own extra steps (searches, queries) folded into one box after the planned work. */
export function fold(nodes: PlanNode[]): PlanNode[] {
  const added = nodes.filter((n) => !n.tool)
  if (!added.length) return nodes
  const planned = nodes.filter((n) => n.tool)
  const last = [...planned].reverse().find((n) => n.tool !== 'canvas')
  const status = added.some((n) => n.status === 'running') ? 'running' : 'verified' // a failed search it worked around isn't a failure
  const more: PlanNode = { index: -1, tool: 'more', label: `+${added.length} more steps the agent added`, risk: 'read',
    after: last ? [last.index] : [], when: '', core: false, skipped: false, status, note: added.at(-1)?.label }
  const design = planned.filter((n) => n.tool === 'canvas').map((n) => ({ ...n, after: [...n.after, -1] }))
  return [...planned.filter((n) => n.tool !== 'canvas'), more, ...design] // layout needs a box before what waits for it
}
