import { describe, expect, it } from 'vitest'
import { themeParams } from './theme'

describe('workspace theme', () => {
  it('maps the agent theme onto AG Studio theme params', () => {
    const p = themeParams({ accent: '#4DFFB2', canvas: '#0E0F0C', palette: ['#111111', '#222222'], font: 'IBM Plex Mono', radius: 6 })
    expect(p).toMatchObject({
      accentColor: '#4DFFB2', studioCanvasBackgroundColor: '#0E0F0C', chartPaletteFills1Color: '#111111',
      chartPaletteFills2Color: '#222222', fontFamily: 'IBM Plex Mono', studioCanvasFontFamily: 'IBM Plex Mono', studioWidgetBorderRadius: 6,
    })
  })

  it('no theme: nothing overridden; unknown keys ignored', () => {
    expect(themeParams({})).toEqual({})
    expect(themeParams({ evil: 'x' } as never)).toEqual({})
  })
})
