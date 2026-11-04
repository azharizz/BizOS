import ReactMarkdown, { type Components } from 'react-markdown'
import { bizos } from './bridge'
import { safeHref } from './format'

// Model output is rendered inert: no raw HTML, no remote images, links open in the default browser.
const components: Components = {
  a: ({ href, children }) => (
    <button type="button" className="md-link" onClick={() => { const u = safeHref(href); if (u) bizos.openExternal(u) }}>
      {children}
    </button>
  ),
  img: ({ alt }) => <span>{alt}</span>,
}

export const Markdown = ({ text }: { text: string }) => (
  <ReactMarkdown skipHtml components={components}>{text}</ReactMarkdown>
)
