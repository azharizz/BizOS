import { describe, expect, it } from 'vitest'
import { heardOutcome, initial, latestStep, reduce, type State } from './state'

const plan = { flow: 'ceo', team: 'Executive', title: 'Is this competitor undercutting us?', subject: 'Lumen', rationale: 'r', steps: ['a', 'b', 'c'], sensed: ['app', 'url'] }
const run = (...events: Parameters<typeof reduce>[1][]): State => events.reduce(reduce, initial)

describe('overlay state machine', () => {
  it('starts collapsed and idle', () => {
    expect(initial.pill).toBe('idle')
    expect(initial.open).toBe(false)
  })

  it('summon opens the panel in listening with fresh context', () => {
    const s = run({ type: 'summon', context: { app: 'Chrome', title: 'Lumen' } })
    expect(s).toMatchObject({ open: true, pill: 'listening', context: { app: 'Chrome' } })
  })

  it('ask -> thinking -> plan -> listening for approval', () => {
    const asked = run({ type: 'summon', context: {} }, { type: 'ask', goal: 'Investigate' })
    expect(asked.pill).toBe('thinking')
    const planned = reduce(asked, { type: 'plan', plan })
    expect(planned.pill).toBe('listening')
    expect(planned.steps.map((s) => s.status)).toEqual(['pending', 'pending', 'pending'])
  })

  it('proceed -> doing, steps verify one by one, workspace and brief stream in', () => {
    let s = run({ type: 'summon', context: {} }, { type: 'ask', goal: 'x' }, { type: 'plan', plan }, { type: 'proceed' })
    expect(s.pill).toBe('doing')
    s = reduce(s, { type: 'step', index: 0, label: 'a', status: 'running' })
    expect(s.current).toBe(0)
    s = reduce(s, { type: 'step', index: 0, label: 'a', status: 'verified', note: '12 rows checked' })
    expect(s.steps[0]).toMatchObject({ status: 'verified', note: '12 rows checked' })
    s = reduce(s, { type: 'workspace', id: 'w1', title: 'T', headline: 'H' })
    s = reduce(s, { type: 'token', text: '**Bold** ' })
    s = reduce(s, { type: 'token', text: 'move.' })
    expect(s.brief).toBe('**Bold** move.')
    s = reduce(s, { type: 'done', workspace_id: 'w1' })
    expect(s.pill).toBe('idle')
    expect(s.workspace?.id).toBe('w1')
  })

  it('steps the agent adds mid-run are appended, and a brief reset clears thinking-aloud text', () => {
    let s = run({ type: 'ask', goal: 'x' }, { type: 'plan', plan }, { type: 'proceed' })
    s = reduce(s, { type: 'step', index: 4, label: 'Query: order trend', status: 'running' })
    expect(s.steps).toHaveLength(4)
    expect(s.steps[3]).toMatchObject({ label: 'Query: order trend', status: 'running' })
    s = reduce(s, { type: 'token', text: 'Let me check…' })
    s = reduce(s, { type: 'brief_reset' })
    expect(s.brief).toBe('')
  })

  it('Always yes is a global setting; an automatic capture is recorded so the user can see it happened', () => {
    let s = run({ type: 'settings', alwaysCapture: true })
    expect(s.alwaysCapture).toBe(true)
    s = reduce(s, { type: 'ask', goal: 'x' })
    s = reduce(s, { type: 'answerConsent', allow: true, auto: true })
    expect(s.captured).toBe('auto')
    expect(reduce(s, { type: 'ask', goal: 'y' }).captured).toBeNull()
  })

  it('asking again keeps the open workspace (follow-ups edit it); New starts fresh', () => {
    let s = run({ type: 'workspace', id: 'w1', title: 'Cloud cost', headline: 'h' }, { type: 'ask', goal: 'make it a donut' })
    expect(s.workspace?.id).toBe('w1')
    s = reduce(s, { type: 'fresh' })
    expect(s.workspace).toBeNull()
    expect(s.fresh).toBe(true)
    expect(reduce(s, { type: 'ask', goal: 'x' }).fresh).toBe(false)
  })

  it('the collapsed step list shows the step being worked on, else the last one that finished', () => {
    let s = run({ type: 'ask', goal: 'x' }, { type: 'plan', plan }, { type: 'proceed' })
    s = reduce(s, { type: 'step', index: 0, label: 'a', status: 'verified' })
    s = reduce(s, { type: 'step', index: 1, label: 'b', status: 'running' })
    expect(latestStep(s)?.label).toBe('b')
    s = reduce(s, { type: 'step', index: 1, label: 'b', status: 'verified' })
    s = reduce(s, { type: 'done', workspace_id: 'w' })
    expect(latestStep(s)?.label).toBe('b')
    expect(latestStep(run({ type: 'ask', goal: 'x' }, { type: 'plan', plan }))).toBeNull()
  })

  it('there are no role tabs: the state has no role', () => {
    expect('role' in initial).toBe(false)
  })

  it('consent request waits for the user', () => {
    const s = run({ type: 'ask', goal: 'x' }, { type: 'consent', reason: 'chart', target: 'Ads', model: 'm' })
    expect(s.pill).toBe('listening')
    expect(s.consent?.target).toBe('Ads')
    expect(reduce(s, { type: 'answerConsent', allow: false }).consent).toBeNull()
  })

  it('errors stop work and surface the message', () => {
    const s = run({ type: 'ask', goal: 'x' }, { type: 'error', message: 'nope' })
    expect(s).toMatchObject({ pill: 'idle', error: 'nope' })
  })

  it('dismiss collapses but keeps finished results', () => {
    const s = run({ type: 'summon', context: {} }, { type: 'workspace', id: 'w', title: 't', headline: 'h' }, { type: 'dismiss' })
    expect(s.open).toBe(false)
    expect(s.workspace?.id).toBe('w')
  })

  it('the mic shows as live only while dictating, not just because the panel is open', () => {
    expect(run({ type: 'summon', context: {} }).dictating).toBe(false)
    const d = run({ type: 'summon', context: {} }, { type: 'dictate' })
    expect(d.dictating).toBe(true)
    expect(reduce(d, { type: 'ask', goal: 'x' }).dictating).toBe(false)
    expect(reduce(d, { type: 'dismiss' }).dictating).toBe(false)
  })

  it('hands-free sends once the speaker pauses, and gives up on silence', () => {
    expect(heardOutcome('', 0, 0, 3000)).toBe('wait')
    expect(heardOutcome('', 0, 0, 10_000)).toBe('nothing')
    expect(heardOutcome('find top llms', 0, 4000, 5000)).toBe('wait') // still talking
    expect(heardOutcome('find top llms', 0, 4000, 6000)).toBe('send')
    expect(heardOutcome('  ', 0, 4000, 6000)).toBe('wait')
  })

  it('hands-free status follows the listener', () => {
    expect(initial.handsFree).toBe('off')
    expect(run({ type: 'handsFree', status: 'starting' }).handsFree).toBe('starting')
    expect(run({ type: 'handsFree', status: 'on' }).handsFree).toBe('on')
  })
})
