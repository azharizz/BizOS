/** BizOS mark: a ledger column and a sensing lens form a "b"; the signal dot is the live insight. */
export function Mark({ size = 20, tile = false, live = false }: { size?: number; tile?: boolean; live?: boolean }) {
  return (
    <svg className="mark" data-live={live || undefined} width={size} height={size} viewBox="0 0 64 64" aria-label="BizOS" role="img">
      {tile && <rect x="2" y="2" width="60" height="60" rx="15" fill="var(--mark-tile, #0E0F0C)" />}
      <g fill="var(--mark-ink, currentColor)">
        <rect x="16" y="13" width="7.5" height="38" rx="3.75" />
        <path fillRule="evenodd" d="M21.25 38.5a14.25 14.25 0 1 0 28.5 0a14.25 14.25 0 1 0 -28.5 0ZM28.75 38.5a6.75 6.75 0 1 0 13.5 0a6.75 6.75 0 1 0 -13.5 0Z" />
      </g>
      <circle className="mark-signal" cx="48" cy="16" r="4.75" fill="#4DFFB2" />
    </svg>
  )
}
