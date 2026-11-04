import '@fontsource-variable/bricolage-grotesque'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './styles/base.css'
import { MotionConfig } from 'motion/react'
import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'

// Two windows, one bundle: the overlay stays light; AG Studio loads only in the workspace window.
const Overlay = lazy(() => import('./overlay/Overlay'))
const Workspace = lazy(() => import('./workspace/Workspace'))
const route = location.hash.slice(1)
const wsId = route.match(/^\/w\/([a-f0-9]+)/)?.[1]
// The route is read once. When the workspace window is pointed at another workspace (a new topic) only the hash
// changes, which doesn't reload the page: reload it so the window really shows the new workspace.
addEventListener('hashchange', () => location.reload())

document.documentElement.dataset.window = wsId ? 'workspace' : 'overlay'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <Suspense>{wsId ? <Workspace id={wsId} /> : <Overlay />}</Suspense>
    </MotionConfig>
  </StrictMode>,
)
