// BizOS service worker: one WebSocket to the BizOS bridge; forwards page reads and actions (click, type, select, scroll) to the tab.
const DEFAULTS = { bridgeUrl: 'ws://127.0.0.1:8787/ext', token: '' }
let socket = null
let connecting = false // pairing, startup and wake-ups can all call connect() at once: open only one socket

async function setStatus(status, extra = {}) {
  await chrome.storage.local.set({ status, statusAt: Date.now(), ...extra })
}

async function connect() {
  if (connecting || (socket && socket.readyState <= WebSocket.OPEN)) return
  connecting = true
  let ws
  try {
    const { bridgeUrl, token } = await chrome.storage.local.get(DEFAULTS)
    if (!token) return setStatus('needs-token')
    ws = socket = new WebSocket(`${bridgeUrl}?token=${encodeURIComponent(token)}`)
  } catch (e) {
    return setStatus('bad-url', { error: String(e) })
  } finally {
    connecting = false
  }
  ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', version: chrome.runtime.getManifest().version, ua: navigator.userAgent }))
  ws.onmessage = async (m) => {
    const msg = JSON.parse(m.data)
    if (msg.type === 'welcome') return setStatus('connected')
    if (!msg.op) return
    const reply = await handle(msg).catch((e) => ({ ok: false, error: String(e?.message ?? e) }))
    ws.send(JSON.stringify({ id: msg.id, ...reply }))
    await chrome.storage.local.set({ lastOp: `${msg.op} · ${new Date().toLocaleTimeString()}` })
  }
  ws.onclose = (e) => {
    if (socket === ws) socket = null // an older socket closing must not drop the current one
    setStatus(e.code === 4401 ? 'bad-token' : 'disconnected')
  }
}

const isWeb = (t) => /^https?:/.test(t?.url ?? '')

// The page the user means: the active tab if it's a website, otherwise the website tab they used most recently
// (chrome://extensions, the new-tab page and the extension popup itself can't be read).
async function activeTab() {
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true, windowType: 'normal' })
  if (isWeb(active)) return active
  const recent = (await chrome.tabs.query({ windowType: 'normal' })).filter(isWeb).sort((a, b) => (b.lastAccessed ?? 0) - (a.lastAccessed ?? 0))[0]
  if (recent) return recent
  throw new Error(`no website tab is open (the active tab is ${active?.url?.split('/')[0] || 'a browser page'})`)
}

// Acting (open/search) uses a new tab the user can see; it waits for the page to load, then reads it.
function loaded(tabId, ms = 20_000) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listen); clearTimeout(timer); setTimeout(resolve, 700) }
    const listen = (id, info) => id === tabId && info.status === 'complete' && done()
    const timer = setTimeout(done, ms)
    chrome.tabs.onUpdated.addListener(listen)
  })
}

// One BizOS tab per browser session: each search/page replaces the last instead of piling up tabs.
async function agentTab(url) {
  const { agentTabId } = await chrome.storage.session.get('agentTabId')
  if (agentTabId) {
    try { return await chrome.tabs.update(agentTabId, { url, active: true }) } catch { /* user closed it */ }
  }
  const tab = await chrome.tabs.create({ url, active: true })
  await chrome.storage.session.set({ agentTabId: tab.id })
  return tab
}

async function openAndRead(url, op) {
  if (!/^https?:\/\//.test(url)) throw new Error('only http(s) pages can be opened')
  const tab = await agentTab(url)
  await loaded(tab.id)
  return ask(tab, op, {})
}

async function ask(tab, op, args) {
  try {
    return await chrome.tabs.sendMessage(tab.id, { op, args })
  } catch {
    // Tabs opened before the extension was installed have no content script yet.
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content_script.js'] })
    return chrome.tabs.sendMessage(tab.id, { op, args })
  }
}

async function handle({ op, args }) {
  if (op === 'open') return openAndRead(String(args.url), 'snapshot')
  if (op === 'search') return openAndRead(`https://www.google.com/search?q=${encodeURIComponent(String(args.query))}`, 'results')
  const tab = await activeTab()
  const reply = await ask(tab, op, args)
  // A click or a submit may load a new page: wait for it, then say where we are now.
  if (reply?.ok && (op === 'click' || (op === 'type' && args.submit))) {
    await Promise.race([loaded(tab.id, 8000), new Promise((r) => setTimeout(r, 1200))])
    const now = await chrome.tabs.get(tab.id)
    reply.result = { ...reply.result, url: now.url, title: now.title }
  }
  return reply
}

// MV3 workers sleep: keep the socket busy while open, and retry every minute while closed.
setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send('{"type":"ping"}'), 20_000)
chrome.alarms.create('bizos-reconnect', { periodInMinutes: 0.5 })
chrome.alarms.onAlarm.addListener(connect)
chrome.runtime.onStartup.addListener(connect)
chrome.runtime.onInstalled.addListener(connect)
chrome.storage.onChanged.addListener((changes) => {
  if (changes.bridgeUrl || changes.token) {
    socket?.close()
    socket = null
    connect()
  }
})
async function pair(token, bridgeUrl) {
  await chrome.storage.local.set({ token, bridgeUrl })
  socket?.close()
  socket = null
  await connect()
  for (let i = 0; i < 20; i++) { // up to 4s for the bridge to say welcome
    const { status } = await chrome.storage.local.get('status')
    if (status === 'connected') return { status }
    await new Promise((r) => setTimeout(r, 200))
  }
  return { status: 'pending' }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type === 'pair') pair(msg.token, msg.bridgeUrl).then(reply)
  if (msg?.type === 'reconnect') connect().then(() => reply(true))
  if (msg?.type === 'preview') handle({ op: 'snapshot', args: {} }).then(reply, (e) => reply({ ok: false, error: String(e.message ?? e) }))
  return true
})
connect()
