import type { AgReportState } from 'ag-studio'
import type { PlanNode } from '../plan/graph'
import type { WorkspaceTheme } from './theme'

export interface ActionSpec {
  id: string
  kind: 'payout' | 'invoice_reminder' | 'draft' | 'paypal' | 'calendar'
  label: string
  amount: number
  currency: string
  recipient: string
  email?: string
  source: string
  why: string
  // the general PayPal tool
  endpoint?: string
  tier?: 'act' | 'money'
  request?: string
  body?: Record<string, unknown>
  step?: number | null // the plan step that proposed it
  status?: 'executed' | 'previewed-only' | 'failed'
  result?: Result
}

export interface Preview extends ActionSpec { mode: 'sandbox' | 'preview-only' | 'draft' | 'local'; idempotency_key: string }
export interface Result { status: string; reference: string | null; link?: string | null }
export interface Page { id: string; title: string }

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
  pages: Page[]
  theme: WorkspaceTheme
  plan: { subject: string; nodes: PlanNode[] } | null
  content: Record<string, Record<string, unknown>> // BizOS widgets' content, by widget id
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
  pages?: Page[]
  theme?: WorkspaceTheme
}
