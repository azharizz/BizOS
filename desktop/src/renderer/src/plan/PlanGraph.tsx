import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { layout, type PlanNode } from './graph'
import './plan.css'

const RISK = { read: 'Reads', act: 'Changes', risky: 'Asks first', money: 'PayPal · you approve' } as Record<string, string>
const STATUS = { approval: 'Waiting for your approval', running: 'Running', verified: 'Done', failed: 'Failed' } as Record<string, string>

type StepData = { n: PlanNode; skipped: boolean; toggle?: () => void }

function Step({ data }: NodeProps<Node<StepData>>) {
  const { n, skipped, toggle } = data
  const optional = !!toggle && !n.core && n.tool !== 'canvas'
  return (
    <div className="pg-node" data-risk={n.risk} data-status={skipped ? 'skipped' : n.status}
      title={[RISK[n.risk], STATUS[n.status], n.note].filter(Boolean).join(' · ')}>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <span className="pg-dot" />
      <span className="pg-label">{n.label}</span>
      {n.note && !skipped && <span className="pg-note">{n.note}</span>}
      {optional && (
        <button className="pg-skip nodrag" onClick={toggle} aria-pressed={!skipped} title={skipped ? 'Add this step back' : 'Skip this step'}>
          {skipped ? '+' : '×'}
        </button>
      )}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

const nodeTypes = { step: Step }

/** The plan as a graph: each box a step (colour = risk, fill = status), arrows = what waits for what, labels = branches. */
export function PlanGraph({ nodes, skip = [], onToggle, height = 260, interactive = false }: {
  nodes: PlanNode[]; skip?: number[]; onToggle?: (index: number) => void; height?: number | string; interactive?: boolean
}) {
  const { positions, edges } = layout(nodes)
  const flowNodes: Node<StepData>[] = nodes.map((n) => ({
    id: String(n.index), type: 'step', position: positions[n.index], draggable: interactive,
    data: { n, skipped: n.skipped || skip.includes(n.index), toggle: onToggle && (() => onToggle(n.index)) },
  }))
  const flowEdges: Edge[] = edges.map((e) => {
    const target = nodes.find((n) => String(n.index) === e.target)
    return { ...e, animated: target?.status === 'running', className: 'pg-edge', labelBgPadding: [6, 3] as [number, number], labelBgBorderRadius: 6 }
  })
  return (
    <div className="pg" style={{ height }}>
      <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12, maxZoom: 1 }}
        // Inside AG Studio the widget gets its real size a moment after mount: fit again once it has it.
        onInit={(rf) => [150, 600].forEach((ms) => setTimeout(() => void rf.fitView({ padding: 0.12, maxZoom: 1 }), ms))}
        nodesConnectable={false} elementsSelectable={false} panOnDrag={interactive} zoomOnScroll={interactive}
        zoomOnPinch={interactive} zoomOnDoubleClick={false} preventScrolling={interactive} proOptions={{ hideAttribution: true }}>
        {interactive && <Background gap={18} size={1} />}
      </ReactFlow>
    </div>
  )
}
