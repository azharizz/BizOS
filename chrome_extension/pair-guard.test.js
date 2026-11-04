// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://evil.example/pair"}
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it, vi } from 'vitest'

it('a public website cannot pair the extension to its own bridge', async () => {
  document.head.innerHTML = '<meta name="bizos-pair" content="x" data-bridge="wss://evil.example/steal">'
  const sendMessage = vi.fn()
  globalThis.chrome = { runtime: { sendMessage, onMessage: { addListener() {} } } }
  new Function(readFileSync(join(import.meta.dirname, 'content_script.js'), 'utf8'))()
  await new Promise((r) => setTimeout(r, 0))
  expect(sendMessage).not.toHaveBeenCalled()
})
