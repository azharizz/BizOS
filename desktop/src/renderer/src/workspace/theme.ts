/** A workspace's own look (set by the agent or the user): BizOS theme keys -> AG Studio theme params. */
export interface WorkspaceTheme {
  accent?: string
  background?: string
  canvas?: string
  widget?: string
  border?: string
  text?: string
  palette?: string[]
  font?: string
  radius?: number
}

const COLOURS: Record<string, string[]> = {
  accent: ['accentColor'],
  background: ['backgroundColor'],
  canvas: ['studioCanvasBackgroundColor'],
  widget: ['studioWidgetBackgroundColor'],
  border: ['borderColor'],
  text: ['foregroundColor'],
}

export function themeParams(t: WorkspaceTheme): Record<string, string | number> {
  const p: Record<string, string | number> = {}
  for (const [k, keys] of Object.entries(COLOURS)) {
    const v = t[k as keyof WorkspaceTheme]
    if (typeof v === 'string') keys.forEach((key) => (p[key] = v))
  }
  t.palette?.slice(0, 7).forEach((c, i) => (p[`chartPaletteFills${i + 1}Color`] = c))
  if (t.font) for (const key of ['fontFamily', 'studioCanvasFontFamily', 'studioWidgetTitleFontFamily']) p[key] = t.font
  if (typeof t.radius === 'number') p.studioWidgetBorderRadius = t.radius
  return p
}
