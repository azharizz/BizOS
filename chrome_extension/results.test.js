// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://www.google.com/search?q=cheap+llm"}
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, it } from 'vitest'

it('reads search results: title, link and snippet, skipping the search engine itself', () => {
  document.body.innerHTML = `
    <div class="g"><a href="https://example.com/llm-prices"><h3>LLM price list Oct 2026</h3></a><div>Cheapest new models compared.</div></div>
    <div class="g"><a href="https://models.example.org/new"><h3>New models this month</h3></a><div>Release tracker.</div></div>
    <a href="https://www.google.com/preferences"><h3>Settings</h3></a>`
  new Function(readFileSync(join(import.meta.dirname, 'content_script.js'), 'utf8'))()
  const r = globalThis.BizOSDom.results({})
  expect(r.results.map((x) => x.url)).toEqual(['https://example.com/llm-prices', 'https://models.example.org/new'])
  expect(r.results[0]).toMatchObject({ title: 'LLM price list Oct 2026' })
  expect(r.results[0].snippet).toContain('Cheapest new models')
})
