const HINTS = {
  connected: 'BizOS reads this tab only when you summon it (⌘⇧Space).',
  'needs-token': 'In the BizOS overlay, click "Connect Chrome" in the footer. It pairs this extension in one click.',
  'bad-token': 'Pairing expired. Click "Connect Chrome" in the BizOS overlay again.',
  'bad-url': 'The bridge URL is invalid. Check Settings.',
  disconnected: 'BizOS desktop is not running, or Chrome is waiting for you to allow local network access (click Allow on the prompt). Retrying…',
}
const $ = (id) => document.getElementById(id)

async function render() {
  const { status = 'disconnected', lastOp = '' } = await chrome.storage.local.get(['status', 'lastOp'])
  $('dot').dataset.s = status
  $('status').textContent = status === 'connected' ? 'Connected' : status.replace('-', ' ')
  $('hint').textContent = HINTS[status] ?? ''
  $('last').textContent = lastOp ? `Last read: ${lastOp}` : ''
}

$('preview').onclick = async () => {
  $('page').textContent = 'Reading…'
  const r = await chrome.runtime.sendMessage({ type: 'preview' })
  const s = r?.result
  $('page').textContent = r?.ok
    ? `${s.title}\n${s.url}\n${s.headings.length} headings · ${s.tables.length} tables · ${s.prices.length} prices · ${s.text.length} chars`
    : r?.error ?? 'Could not read this page'
}
$('options').onclick = () => chrome.runtime.openOptionsPage()
chrome.storage.onChanged.addListener(render)
chrome.runtime.sendMessage({ type: 'reconnect' })
render()
