const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumSignificantDigits: 3 })

export function formatValue(v: number, unit: string): string {
  switch (unit) {
    case '$':
      return `${v < 0 ? '-' : ''}$${compact.format(Math.abs(v))}`
    case '%':
      return `${v.toFixed(1)}%`
    case 'x':
      return `${v.toFixed(2)}×`
    case 'd':
      return `${v.toFixed(1)}d`
    default:
      return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toFixed(1)
  }
}

export const money = (v: number, currency = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(v)

/** Model output is untrusted: only http(s) links may leave the app, and only to the default browser. */
export function safeHref(href?: string): string | null {
  try {
    const { protocol } = new URL(href ?? '')
    return protocol === 'https:' || protocol === 'http:' ? href! : null
  } catch {
    return null
  }
}
