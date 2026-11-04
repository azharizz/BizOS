// BizOS content script: read-only DOM exploration of the page the user is on.
// Answers {op, args} from the service worker. Never clicks, types or changes the page (that is Phase 2).

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

  const OPS = {
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
