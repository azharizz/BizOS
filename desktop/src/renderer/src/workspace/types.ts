import type { AgReportState } from 'ag-studio'


export interface ActionSpec {
  id: string
  kind: 'payout' | 'invoice_reminder' | 'draft'
  label: string
  amount: number
  currency: string
  recipient: string
  email?: string
  source: string
  why: string
}

export interface Preview extends ActionSpec { mode: 'sandbox' | 'preview-only' | 'draft'; idempotency_key: string }
export interface Result { status: string; reference: string | null; link?: string }

export interface WorkspaceMeta {
  id: string
  title: string
  headline: string
  narrative: string
  complete: boolean
  actions: ActionSpec[]
  risks: string[]
  agent_version: number
  runs: { goal: string; flow: string }[]
  sources: string[]
}

export interface WorkspaceSpec {
  id: string
  flow: string
  title: string
  headline: string
  actions: ActionSpec[]
  risks: string[]
  data: { sources: { id: string; name: string; data: Record<string, unknown>[]; fields: { id: string; name: string; format: string }[] }[] }
  state: AgReportState
  narrative: string
  complete: boolean
  agent_version: number
}
