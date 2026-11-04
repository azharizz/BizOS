// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'

const SOURCE = readFileSync(join(import.meta.dirname, 'content_script.js'), 'utf8')
let clicked = []

beforeAll(() => {
  document.body.innerHTML = `
    <form id="f"><label for="q">Search products</label><input id="q" name="q">
      <input type="password" name="pw" aria-label="Password">
      <input name="cardnumber" autocomplete="cc-number" aria-label="Card">
      <select aria-label="Sort"><option>Relevance</option><option>Price: low to high</option></select>
      <button type="submit">Place order</button></form>
    <form id="g"><input name="email" aria-label="Email"><button type="submit">Go</button></form>
    <form id="s2" role="search"><input name="term" aria-label="Find"><button type="submit">Search</button></form>
    <a href="#more">Show more results</a>
    <button style="display:none">Hidden</button>
    <div role="button" tabindex="0">Filters</div>`
  document.getElementById('f').addEventListener('submit', (e) => { e.preventDefault(); clicked.push('submitted') })
  document.querySelector('a').addEventListener('click', (e) => { e.preventDefault(); clicked.push('more') })
  new Function(SOURCE)()
})

const dom = () => globalThis.BizOSDom
const ref = (label) => dom().elements().elements.find((e) => e.label === label).ref

describe('content script page actions', () => {
  it('numbers the visible things you can click or type in, with labels and risk', () => {
    const { elements } = dom().elements()
    const labels = elements.map((e) => e.label)
    expect(labels).toEqual(expect.arrayContaining(['Search products', 'Sort', 'Place order', 'Show more results', 'Filters']))
    expect(labels).not.toContain('Hidden')
    expect(elements.find((e) => e.label === 'Place order').risky).toBe(true) // submits a form / buys
    expect(elements.find((e) => e.label === 'Show more results').risky).toBe(false)
    expect(elements.find((e) => e.label === 'Password').blocked).toBe(true)
    expect(elements.find((e) => e.label === 'Card').blocked).toBe(true)
  })

  it('clicks, types, selects', () => {
    clicked = []
    dom().click({ ref: ref('Show more results') })
    expect(clicked).toEqual(['more'])
    dom().type({ ref: ref('Search products'), text: 'cold brew' })
    expect(document.getElementById('q').value).toBe('cold brew')
    dom().select({ ref: ref('Sort'), option: 'price: low' })
    expect(document.querySelector('select').value).toBe('Price: low to high')
  })

  it('never types into password or payment fields', () => {
    expect(() => dom().type({ ref: ref('Password'), text: 'x' })).toThrow(/password|payment/)
    expect(() => dom().type({ ref: ref('Card'), text: '4111' })).toThrow(/password|payment/)
  })

  it('submitting is explicit and the caller is told it was risky', () => {
    clicked = []
    const r = dom().type({ ref: ref('Search products'), text: 'tea', submit: true })
    expect(clicked).toEqual(['submitted'])
    expect(r.submitted).toBe(true)
  })

  it('knows a search box from a form that might send or buy', () => {
    expect(dom().risk({ ref: ref('Search products') }).search).toBe(true)
    expect(dom().risk({ ref: ref('Place order') }).search).toBe(true) // inside the search form here, but...
    expect(dom().risk({ ref: ref('Place order') }).risky).toBe(true) // ...its label says it orders: still asked
  })

  it('a search button is safe; a plain submit in another form is not', () => {
    const els = dom().elements().elements
    expect(els.find((e) => e.label === 'Search').risky).toBe(false)
    expect(els.find((e) => e.label === 'Go').risky).toBe(true)
  })

  it('unknown refs fail clearly (the page changed: read elements again)', () => {
    expect(() => dom().click({ ref: 999 })).toThrow(/elements again/)
  })
})
