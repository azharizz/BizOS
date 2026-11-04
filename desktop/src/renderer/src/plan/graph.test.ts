import { describe, expect, it } from 'vitest'
import { fold, layout, withActions, type PlanNode } from './graph'

const node = (index: number, after: number[], extra: Partial<PlanNode> = {}): PlanNode => ({
  index, tool: 'run_sql', label: `Step ${index}`, risk: 'read', after, when: '', core: false, skipped: false, status: 'pending', ...extra,
})

describe('plan graph layout', () => {
  it('puts each step one row below the steps it waits for, and parallel steps side by side', () => {
    const nodes = [node(0, []), node(1, [0]), node(2, [0]), node(3, [1, 2])]
    const { positions, edges } = layout(nodes)
    expect(positions[0].y).toBeLessThan(positions[1].y)
    expect(positions[1].y).toBe(positions[2].y) // a branch: same row
    expect(positions[1].x).not.toBe(positions[2].x)
    expect(positions[3].y).toBeGreaterThan(positions[1].y)
    expect(edges.map((e) => `${e.source}->${e.target}`)).toEqual(['0->1', '0->2', '1->3', '2->3'])
  })

  it('labels branch edges with their condition and ignores links to unknown steps', () => {
    const { edges } = layout([node(0, []), node(1, [0, 9], { when: 'if cheaper' })])
    expect(edges).toEqual([{ id: '0-1', source: '0', target: '1', label: 'if cheaper' }])
  })

  it('a straight plan is one column', () => {
    const { positions } = layout([node(0, []), node(1, [0]), node(2, [1])])
    expect(new Set(Object.values(positions).map((p) => p.x)).size).toBe(1)
  })
})

describe('PayPal approvals on the graph', () => {
  it('a proposal waits for a person, then turns green (or red) when the action runs', () => {
    const nodes = [node(0, [], { tool: 'paypal_propose', risk: 'money', status: 'verified' })]
    expect(withActions(nodes, [{ id: 'pp-1', step: 0 }])[0].status).toBe('approval')
    expect(withActions(nodes, [{ id: 'pp-1', step: 0, status: 'executed' }])[0]).toMatchObject({ status: 'verified', note: 'approved' })
    expect(withActions(nodes, [{ id: 'pp-1', step: 0, status: 'failed' }])[0].status).toBe('failed')
    expect(withActions(nodes, [])[0].status).toBe('verified')
  })
})

describe('steps the agent added along the way', () => {
  it('fold into one box after the planned work, so the planned shape stays readable', () => {
    const nodes = [node(0, []), node(1, [0], { tool: 'paypal_propose' }), node(2, [1], { tool: 'canvas' }),
      node(3, [0], { tool: '', label: 'Query: a', status: 'verified' }), node(4, [3], { tool: '', label: 'Search: b', status: 'running' })]
    const out = fold(nodes)
    expect(out.map((n) => n.index)).toEqual([0, 1, -1, 2])
    expect(out[2]).toMatchObject({ label: '+2 more steps the agent added', status: 'running', after: [1] })
    expect(out[3].after).toEqual([1, -1]) // the design waits for them too
    expect(fold(nodes.slice(0, 3))).toEqual(nodes.slice(0, 3))
    expect(layout(out).positions[2].y).toBeGreaterThan(layout(out).positions[-1].y)
  })
})
