// BizOS content script: reads the page, and acts on it when the agent asks (click, type, select, scroll).
// Answers {op, args} from the service worker. Never touches password or payment fields. Elements that submit, send,
// buy or delete are marked risky: the backend asks the user before clicking them.

// One-click pairing: the local BizOS pairing page carries the token. Only trusted when the page itself is local
// and the bridge is local, so no website can point the extension at its own server.
;(() => {
  const LOCAL = /^(127\.0\.0\.1|localhost)$/
  const meta = document.querySelector('meta[name="bizos-pair"]')
  if (!meta || !LOCAL.test(location.hostname) || location.pathname !== '/pair') return
  const bridgeUrl = meta.dataset.bridge ?? ''
  let host = ''
  try { host = new URL(bridgeUrl).hostname } catch { return }
  if (!/^wss?:/.test(bridgeUrl) || !LOCAL.test(host)) return
  const status = document.getElementById('pair-status')
  globalThis.chrome?.runtime?.sendMessage({ type: 'pair', token: meta.content, bridgeUrl }).then((r) => {
    if (!status) return
    status.textContent = r?.status === 'connected' ? 'Connected ✓ You can close this tab.'
      : 'Saved. Connecting… if Chrome asks about your local network, click Allow.'
    document.getElementById('pair-help')?.remove()
  })
})()

;(() => {
  if (globalThis.__bizosDom) return
  globalThis.__bizosDom = true

  const PRICE = /(?:[$€£¥]|USD|EUR|IDR|Rp\.?)\s?\d[\d.,]*/g
  const clip = (s, n) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n)
  const textOf = (el) => clip(el.innerText ?? el.textContent, 4000)

  function selectorOf(el) {
    if (el.id) return `#${CSS.escape(el.id)}`
    const parts = []
    for (let e = el; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      const same = [...(e.parentElement?.children ?? [])].filter((c) => c.tagName === e.tagName)
      parts.unshift(same.length > 1 ? `${e.tagName.toLowerCase()}:nth-of-type(${same.indexOf(e) + 1})` : e.tagName.toLowerCase())
    }
    return ['body', ...parts].join(' > ')
  }

  function tables(limit = 5) {
    return [...document.querySelectorAll('table')].slice(0, limit).map((t) => ({
      caption: clip(t.caption?.textContent, 120),
      rows: [...t.rows].slice(0, 50).map((r) => [...r.cells].map((c) => clip(c.textContent, 80))),
    }))
  }

  function prices(limit = 40) {
    const out = []
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let n = walk.nextNode(); n && out.length < limit; n = walk.nextNode()) {
      for (const price of n.textContent.match(PRICE) ?? []) {
        const box = n.parentElement?.closest('[itemtype*="Product"], [class*="product"], li, article, tr') ?? n.parentElement
        out.push({ price, context: clip(box?.textContent, 140) })
      }
    }
    return out
  }

  // ---- acting on the page: elements are numbered (data-bizos-ref) so the agent says "click 12", not a selector
  const INTERACTIVE = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], [contenteditable=""], [contenteditable=true]'
  const RISKY = /\b(submit|send|post|publish|buy|order|pay|checkout|purchase|delete|remove|confirm|transfer|subscribe|sign ?up|book|reserve|donate|unsubscribe)\b/i
  const SECRET = /pass(word)?|card|cc-|cvc|cvv|iban|security code|expir|pin\b|otp|one-time/i
  let refs = []

  const visible = (el) => {
    const s = getComputedStyle(el)
    return s.display !== 'none' && s.visibility !== 'hidden' && !el.closest('[hidden], [aria-hidden=true]')
  }
  function labelOf(el) {
    return clip(el.getAttribute('aria-label') || el.labels?.[0]?.textContent ||
      (el.tagName === 'INPUT' ? el.value : '') || el.textContent || el.getAttribute('placeholder') ||
      el.getAttribute('title') || el.name || '', 80)
  }
  const blocked = (el) => el.type === 'password' || SECRET.test(`${el.name} ${el.autocomplete} ${el.id} ${labelOf(el)}`)
  const searchy = (el) => /search|find|query|filter/i.test(`${el.type} ${el.name} ${el.id} ${labelOf(el)}`) || el.name === 'q'
  // A search form only searches: submitting it is safe. Other forms may send, sign up or buy.
  const searchForm = (form) => !!form && (form.getAttribute('role') === 'search' || [...form.elements].some(searchy))
  const submits = (el) => el.type === 'submit' || (el.tagName === 'BUTTON' && !!el.form && el.type !== 'button')
  const risky = (el) => RISKY.test(labelOf(el)) || (submits(el) && !searchForm(el.form))

  function find(ref) {
    const el = refs[ref]
    if (!el || !el.isConnected) throw new Error(`no element ${ref} on the page any more: read elements again`)
    return el
  }
  const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }))

  const OPS = {
    elements: ({ limit = 120 } = {}) => {
      refs = [...document.querySelectorAll(INTERACTIVE)].filter(visible).slice(0, limit)
      return {
        url: location.href, title: document.title,
        elements: refs.map((el, ref) => {
          el.dataset.bizosRef = ref
          const tag = el.tagName.toLowerCase()
          return { ref, tag, type: el.type || el.getAttribute('role') || '', label: labelOf(el), risky: risky(el), blocked: blocked(el),
            ...(tag === 'select' ? { options: [...el.options].map((o) => clip(o.text, 40)).slice(0, 20) } : {}),
            ...(el.href ? { href: el.href } : {}) }
        }),
      }
    },
    click: ({ ref }) => {
      const el = find(ref)
      el.scrollIntoView?.({ block: 'center' }) // so the user sees what is clicked
      el.click()
      return { clicked: labelOf(el) }
    },
    type: ({ ref, text, submit = false }) => {
      const el = find(ref)
      if (blocked(el)) throw new Error('BizOS never types into password or payment fields')
      el.focus()
      if (el.isContentEditable) el.textContent = String(text)
      else el.value = String(text)
      fire(el, 'input')
      fire(el, 'change')
      if (submit) el.form ? el.form.requestSubmit() : el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
      return { typed: labelOf(el), submitted: !!submit }
    },
    select: ({ ref, option }) => {
      const el = find(ref)
      const o = [...el.options].find((x) => x.text.toLowerCase().includes(String(option).toLowerCase()))
      if (!o) throw new Error(`no option like "${option}"`)
      el.value = o.value
      fire(el, 'change')
      return { selected: o.text }
    },
    scroll: ({ direction = 'down' }) => {
      scrollBy({ top: (direction === 'up' ? -1 : 1) * innerHeight * 0.8, behavior: 'instant' })
      return { scrolled: direction, y: Math.round(scrollY) }
    },
    risk: ({ ref }) => {
      const el = find(ref)
      // A search box: submitting it only searches, so it needs no confirmation (other forms may send or buy).
      const search = searchy(el) || searchForm(el.form) || !!el.closest('[role=search]')
      return { label: labelOf(el), risky: risky(el), blocked: blocked(el), search }
    },

    snapshot: () => ({
      url: location.href,
      title: document.title,
      selection: clip(getSelection()?.toString(), 2000),
      description: document.querySelector('meta[name="description"]')?.content ?? '',
      headings: [...document.querySelectorAll('h1, h2, h3')].slice(0, 30).map((h) => clip(h.textContent, 120)),
      text: clip(document.body.innerText ?? document.body.textContent, 8000),
      tables: tables(),
      prices: prices(),
    }),
    query: ({ selector, limit = 20 }) =>
      [...document.querySelectorAll(selector)].slice(0, limit).map((el) => ({
        selector: selectorOf(el), tag: el.tagName.toLowerCase(), text: clip(textOf(el), 300), href: el.href ?? null,
      })),
    // Search results on any engine: links that wrap a heading, minus the engine's own pages.
    results: ({ limit = 10 }) => {
      const seen = new Set()
      const results = []
      for (const h of document.querySelectorAll('a h3, a h2')) {
        const a = h.closest('a')
        if (!a?.href || !/^https?:/.test(a.href) || new URL(a.href).hostname === location.hostname || seen.has(a.href)) continue
        seen.add(a.href)
        const box = a.closest('div.g, [data-hveid], li, article') ?? a.parentElement
        results.push({ title: clip(h.textContent, 160), url: a.href, snippet: clip((box?.textContent ?? '').replace(h.textContent, ''), 280) })
        if (results.length >= limit) break
      }
      return { url: location.href, title: document.title, results }
    },
    find: ({ text, limit = 15 }) => {
      const needle = String(text).toLowerCase()
      const seen = new Set()
      const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
      for (let n = walk.nextNode(); n && seen.size < limit; n = walk.nextNode()) {
        if (n.textContent.toLowerCase().includes(needle) && n.parentElement) seen.add(n.parentElement)
      }
      return [...seen].map((el) => ({ selector: selectorOf(el), tag: el.tagName.toLowerCase(), text: clip(textOf(el), 300) }))
    },
  }

  globalThis.BizOSDom = OPS
  globalThis.chrome?.runtime?.onMessage?.addListener((msg, _sender, reply) => {
    try {
      if (!OPS[msg?.op]) throw new Error(`unknown op ${msg?.op}`)
      reply({ ok: true, result: OPS[msg.op](msg.args ?? {}) })
    } catch (e) {
      reply({ ok: false, error: String(e?.message ?? e) })
    }
  })
})()
