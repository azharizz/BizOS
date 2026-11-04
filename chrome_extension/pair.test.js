// @vitest-environment jsdom
// @vitest-environment-options {"url": "http://127.0.0.1:8787/pair?code=abc"}
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it, vi } from 'vitest'

const SOURCE = readFileSync(join(import.meta.dirname, 'content_script.js'), 'utf8')

it('the local pairing page hands the token to the extension, no copy-paste', async () => {
  document.head.innerHTML = '<meta name="bizos-pair" content="tok-123" data-bridge="ws://127.0.0.1:8787/ext">'
  document.body.innerHTML = '<p id="pair-status">Connecting…</p>'
  const sendMessage = vi.fn().mockResolvedValue({ status: 'connected' })
  globalThis.chrome = { runtime: { sendMessage, onMessage: { addListener() {} } } }
  new Function(SOURCE)()
  await new Promise((r) => setTimeout(r, 0))
  expect(sendMessage).toHaveBeenCalledWith({ type: 'pair', token: 'tok-123', bridgeUrl: 'ws://127.0.0.1:8787/ext' })
  expect(document.getElementById('pair-status').textContent).toMatch(/Connected/)
})
