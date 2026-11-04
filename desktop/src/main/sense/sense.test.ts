import { describe, expect, it } from 'vitest'
import { createSense } from './index'
import { parseMac } from './mac'
import { parseWin } from './win'

const SEP = '\u001f'

describe('sense adapter factory', () => {
  it('picks one adapter per OS behind the same interface', () => {
    for (const os of ['darwin', 'win32'] as const) {
      const s = createSense(os)
      expect(typeof s.read).toBe('function')
      expect(typeof s.capture).toBe('function')
    }
    expect(() => createSense('linux')).toThrow(/not supported/)
  })
})

describe('macOS parsing', () => {
  it('maps the AppleScript record to context fields and drops blanks', () => {
    const out = ['Google Chrome', 'Lumen Supply – Cold Brew', 'https://www.competitor1.example/p', 'Cold Brew 1L', 'Price $8.40', ''].join(SEP)
    expect(parseMac(out, 'clip')).toEqual({
      app: 'Google Chrome', title: 'Lumen Supply – Cold Brew', url: 'https://www.competitor1.example/p',
      selection: 'Cold Brew 1L', text: 'Price $8.40', clipboard: 'clip',
    })
  })

  it('survives missing fields', () => {
    expect(parseMac('Finder', '')).toEqual({ app: 'Finder' })
  })
})

describe('Windows parsing', () => {
  it('reads the PowerShell JSON', () => {
    expect(parseWin('{"app":"EXCEL","title":"Stock.xlsx","text":"WH-2"}', '')).toEqual({ app: 'EXCEL', title: 'Stock.xlsx', text: 'WH-2' })
    expect(parseWin('garbage', '')).toEqual({})
  })
})
