import { describe, expect, it } from 'vitest'
import { formatValue, safeHref } from './format'

describe('formatValue', () => {
  it('formats money compactly', () => {
    expect(formatValue(1234567, '$')).toBe('$1.23M')
    expect(formatValue(48210.4, '$')).toBe('$48.2K')
    expect(formatValue(-950, '$')).toBe('-$950')
  })
  it('formats percentages, multiples, days and counts', () => {
    expect(formatValue(52.31, '%')).toBe('52.3%')
    expect(formatValue(2.4, 'x')).toBe('2.40×')
    expect(formatValue(8.4, 'd')).toBe('8.4d')
    expect(formatValue(13, '')).toBe('13')
  })
})

describe('safeHref', () => {
  it('only lets http(s) links out, never javascript: or file:', () => {
    expect(safeHref('https://paypal.com')).toBe('https://paypal.com')
    expect(safeHref('javascript:alert(1)')).toBeNull()
    expect(safeHref('file:///etc/passwd')).toBeNull()
    expect(safeHref(undefined)).toBeNull()
  })
})
