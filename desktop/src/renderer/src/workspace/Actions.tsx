import { useMutation, useQuery } from '@tanstack/react-query'
import { animate, AnimatePresence, motion, useMotionValue, useTransform, type AnimationPlaybackControls } from 'motion/react'
import { useRef, useState } from 'react'
import { api, bizos } from '../lib/bridge'
import { money } from '../lib/format'
import type { ActionSpec, Preview, Result } from './types'

const KIND = { payout: 'PayPal Payout', invoice_reminder: 'PayPal Invoice', draft: 'Draft', paypal: 'PayPal', calendar: 'Calendar' } as const
const words = (s = '') => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const MODE = { sandbox: 'Sandbox', 'preview-only': 'Preview only', draft: 'Draft, no money moves', local: 'On this Mac' } as const
const soft = { type: 'spring', stiffness: 300, damping: 30 } as const

const savedApprover = () => { try { return localStorage.getItem('bizos.approver') ?? '' } catch { return '' } }

export function Actions({ wsId, actions }: { wsId: string; actions: ActionSpec[] }) {
  return (
    <section className="rail-block">
      <h2 className="rail-title">Proposed actions <span>{actions.length}</span></h2>
      <motion.div className="actions" initial="hidden" animate="show" variants={{ show: { transition: { staggerChildren: 0.07, delayChildren: 0.35 } } }}>
        {actions.map((a) => <ActionCard key={a.id} wsId={wsId} a={a} />)}
      </motion.div>
    </section>
  )
}

export function ActionCard({ wsId, a }: { wsId: string; a: ActionSpec }) {
  const ref = { workspace_id: wsId, action_id: a.id }
  const preview = useMutation({ mutationFn: () => api<Preview>('/actions/preview', ref) })
  const execute = useMutation({
    mutationFn: (v: { key: string; by: string }) => api<Result>('/actions/execute', { ...ref, idempotency_key: v.key, approved_by: v.by }),
  })
  const [approver, setApprover] = useState(savedApprover)
  const p = preview.data
  const done = execute.data ?? (a.status && a.status !== 'failed' ? a.result : undefined) // approved earlier (kept after restart)

  const approve = () => {
    if (!p || !approver.trim()) return
    try { localStorage.setItem('bizos.approver', approver.trim()) } catch { /* nicety only */ }
    execute.mutate({ key: p.idempotency_key, by: approver.trim() })
  }

  return (
    <motion.article layout className="action" data-kind={a.kind} data-open={!!p}
      variants={{ hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0 } }} transition={soft}>
      <header className="action-head">
        <span className="action-kind" data-tier={a.tier}>{a.kind === 'paypal' ? `PayPal · ${words(a.endpoint)}` : KIND[a.kind]}</span>
        {a.amount > 0 && <span className="action-amount">{money(a.amount, a.currency)}</span>}
      </header>
      <h3>{a.label}</h3>
      <p className="action-why">{a.why}</p>

      <AnimatePresence mode="wait" initial={false}>
        {done ? (
          <Stamp key="stamp" result={done} mode={p?.mode ?? 'sandbox'} payout={a.kind === 'payout'} live={a.kind === 'paypal' ? { wsId, id: a.id } : null} />
        ) : p ? (
          <motion.div key="preview" className="sheet" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={soft}>
            <dl>
              {p.request && (<><dt>Request</dt><dd className="mono">{p.request}</dd></>)}
              {p.amount > 0 && (<><dt>Amount</dt><dd className="num">{money(p.amount, p.currency)}</dd></>)}
              {p.kind !== 'paypal' && (<><dt>Recipient</dt><dd>{p.recipient}</dd></>)}
              {p.email && (<><dt>Pays to</dt><dd className="mono">{p.email}</dd></>)}
              <dt>Source</dt><dd>{p.source}</dd>
              <dt>Mode</dt><dd><span className="mode" data-mode={p.mode}>{MODE[p.mode]}</span></dd>
              <dt>Key</dt><dd className="mono faint" title="Idempotency key: approving twice never pays twice">{p.idempotency_key.slice(0, 16)}…</dd>
            </dl>
            {p.body && <pre className="sheet-body">{JSON.stringify(p.body, null, 2)}</pre>}
            <p className="sheet-note">{p.kind === 'paypal' ? 'Exactly this request is sent to PayPal, once, when you hold to approve.' : 'Figures come from company records on the server, not from your screen.'}</p>
            <label className="approver">
              <span>Approved by</span>
              <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Your name or email" />
            </label>
            {execute.error && <p className="sheet-error">{execute.error.message}</p>}
            <HoldButton disabled={!approver.trim() || execute.isPending} busy={execute.isPending} onConfirm={approve}
              label={a.kind === 'draft' ? 'Hold to file draft' : a.tier === 'money' ? 'Hold to approve payment' : 'Hold to approve'} />
          </motion.div>
        ) : (
          <motion.button key="review" className="btn-review" onClick={() => preview.mutate()} disabled={preview.isPending}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            {preview.isPending ? 'Preparing preview…' : preview.error ? `Retry: ${preview.error.message}` : 'Review'}
            <svg width="14" height="14" viewBox="0 0 16 16"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </motion.button>
        )}
      </AnimatePresence>
    </motion.article>
  )
}

/** Press and hold to confirm: an accidental click can never move money. */
function HoldButton({ onConfirm, disabled, busy, label }: { onConfirm: () => void; disabled: boolean; busy: boolean; label: string }) {
  const progress = useMotionValue(0)
  const width = useTransform(progress, (v) => `${v * 100}%`)
  const run = useRef<AnimationPlaybackControls | null>(null)
  const start = () => {
    if (disabled) return
    run.current = animate(progress, 1, { duration: 1.1, ease: 'linear', onComplete: onConfirm })
  }
  const stop = () => {
    if (progress.get() >= 1) return
    run.current?.stop()
    animate(progress, 0, { duration: 0.3, ease: 'easeOut' })
  }
  return (
    <button className="hold" disabled={disabled} onPointerDown={start} onPointerUp={stop} onPointerLeave={stop}
      onKeyDown={(e) => (e.key === ' ' || e.key === 'Enter') && !e.repeat && start()} onKeyUp={stop}>
      <motion.span className="hold-fill" style={{ width }} />
      <span className="hold-label">{busy ? 'Executing…' : label}</span>
    </button>
  )
}

function Stamp({ result, mode, payout, live: at }: { result: Result; mode: Preview['mode']; payout: boolean; live: { wsId: string; id: string } | null }) {
  // Payouts settle asynchronously at PayPal: poll the real item status until it leaves PENDING.
  const live = useQuery({
    queryKey: ['payout', result.reference],
    queryFn: () => api<{ batch: string; item: string | null; errors: string | null }>(`/paypal/payouts/${result.reference}`),
    enabled: payout && mode === 'sandbox' && !!result.reference,
    refetchInterval: (q) => (/PENDING|PROCESSING/.test(q.state.data?.item ?? 'PENDING') ? 4000 : false),
  })
  // Anything else the general PayPal tool created (payment link, invoice, refund...): its live status at PayPal.
  const status = useQuery({
    queryKey: ['action-status', at?.id, result.reference],
    queryFn: () => api<{ status: string | null }>('/actions/status', { workspace_id: at!.wsId, action_id: at!.id }),
    enabled: !!at && !!result.reference, refetchInterval: 15_000,
  })
  const word = result.status === 'DRAFTED' ? 'Drafted' : result.status === 'SCHEDULED' ? 'Scheduled' : result.status === 'PREVIEW_ONLY' ? 'Previewed' : 'Approved'
  const [copied, setCopied] = useState(false)
  return (
    <motion.div className="stamp-wrap" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <motion.div className="stamp" data-mode={mode}
        initial={{ scale: 1.9, rotate: -18, opacity: 0, filter: 'blur(3px)' }}
        animate={{ scale: 1, rotate: -5, opacity: 1, filter: 'blur(0px)' }}
        transition={{ type: 'spring', stiffness: 700, damping: 17, mass: 0.9 }}>
        {word}
      </motion.div>
      <div className="stamp-meta">
        <span>{(live.data?.item ?? status.data?.status ?? result.status).replace('_', ' ').toLowerCase()}</span>
        {result.link && (
          <span className="stamp-link">
            <button className="linkish" onClick={() => bizos.openExternal(result.link!)}>Open link</button>
            <button className="linkish" onClick={() => void navigator.clipboard.writeText(result.link!).then(() => setCopied(true))}>{copied ? 'Copied' : 'Copy link'}</button>
          </span>
        )}
        {live.data?.errors && <span className="sheet-error">{live.data.errors}</span>}
        {result.reference && <span className="mono">{result.reference}</span>}
        <span className="faint">Logged to audit trail</span>
      </div>
    </motion.div>
  )
}
