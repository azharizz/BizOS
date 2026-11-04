const DEFAULTS = { bridgeUrl: 'ws://127.0.0.1:8787/ext', token: '' }
const form = document.getElementById('form')

chrome.storage.local.get(DEFAULTS).then((v) => {
  form.bridgeUrl.value = v.bridgeUrl
  form.token.value = v.token
})

form.onsubmit = async (e) => {
  e.preventDefault()
  await chrome.storage.local.set({ bridgeUrl: form.bridgeUrl.value.trim(), token: form.token.value.trim() })
  document.getElementById('saved').textContent = 'Saved. Connecting…'
  setTimeout(async () => {
    const { status } = await chrome.storage.local.get('status')
    document.getElementById('saved').textContent = status === 'connected' ? 'Connected ✓' : `Status: ${status}`
  }, 1500)
}
