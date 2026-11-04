import { studioTheme, type AgDataSourcesDefinition, type AgReportState, type AgStudioApi } from 'ag-studio'
import { AgStudio, AgStudioProvider } from 'ag-studio-react'
import { motion } from 'motion/react'
import { themeParams } from './theme'
import type { WorkspaceSpec } from './types'
import { widgets } from './widgets'

// AG Studio in the BizOS paper palette. Series colours are ordered for contrast, mint first.
const theme = studioTheme.withParams({
  fontFamily: 'Bricolage Grotesque Variable',
  studioCanvasFontFamily: 'Bricolage Grotesque Variable',
  studioWidgetTitleFontFamily: 'Bricolage Grotesque Variable',
  studioWidgetTitleFontSize: 14,
  studioWidgetTitleFontWeight: 620,
  accentColor: '#12B877',
  backgroundColor: '#FBFAF6',
  foregroundColor: '#121310',
  borderColor: '#E2DDD0',
  studioCanvasBackgroundColor: '#F3F0E8',
  studioWidgetBackgroundColor: '#FBFAF6',
  studioWidgetBorderRadius: 16,
  studioWidgetBorder: { width: 1, color: '#E2DDD0' },
  studioWidgetPadding: 10,
  chartPaletteFills1Color: '#3DDC97',
  chartPaletteFills2Color: '#1F3D36',
  chartPaletteFills3Color: '#C9A227',
  chartPaletteFills4Color: '#6E8FA8',
  chartPaletteFills5Color: '#9B5D73',
  chartPaletteFills6Color: '#7FA37A',
  chartPaletteFills7Color: '#3A3A36',
})

/** Data sources (and look) AG Studio was mounted with. Its `data` prop can't add sources later, so new sources remount it. */
export const signature = (ws: WorkspaceSpec) => ws.data.sources.map((s) => `${s.id}:${s.fields.length}`).join('|') + JSON.stringify(ws.theme ?? {})

/** Show another page (the tabs above the canvas): AG Studio keeps the pages, BizOS names them. */
export function showPage(id: string) {
  const state = live.api?.getState()
  if (state && state.selectedPageId !== id) live.api!.setState({ ...state, selectedPageId: id })
}

let live: { api: AgStudioApi | null; signature: string } = { api: null, signature: '' }

/** Agent edited widgets or layout only: apply in place, no remount, no flicker. Returns false if a remount is needed. */
export function applyLive(ws: WorkspaceSpec): boolean {
  if (!live.api || live.signature !== signature(ws)) return false
  live.api.setState(ws.state)
  return true
}

export function Studio({ ws, license, mode, onState }: {
  ws: WorkspaceSpec; license: string; mode: 'view' | 'edit'; onState: (state: AgReportState) => void
}) {
  const sig = signature(ws)
  return (
    <AgStudioProvider licenseKey={license || undefined}>
      <motion.div key={sig} className="studio" initial={{ opacity: 0, scale: 0.995 }} animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
        <AgStudio
          theme={ws.theme && Object.keys(ws.theme).length ? theme.withParams(themeParams(ws.theme)) : theme}
          widgets={widgets}
          data={ws.data as AgDataSourcesDefinition}
          initialState={ws.state}
          mode={mode}
          panels={{ view: {}, edit: { right: ['edit', 'data', 'filters'] } }}
          onApiReady={(e) => { live = { api: e.api, signature: sig } }}
          onStateUpdated={(e) => onState(e.state)}
          style={{ height: '100%', width: '100%' }}
        />
      </motion.div>
    </AgStudioProvider>
  )
}
