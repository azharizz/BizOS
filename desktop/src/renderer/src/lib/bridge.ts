import type { Bridge, Config } from '../../../shared/types'

declare global {
  interface Window { bizos: Bridge }
}

export const bizos = window.bizos
export const config: Promise<Config> = bizos.config()

/** REST call to the backend with the per-launch token. Throws with the server's message. */
export async function api<T>(path: string, body?: unknown, method?: 'PUT'): Promise<T> {
  const { backendUrl, token } = await config
  const r = await fetch(backendUrl + path, {
    method: method ?? (body === undefined ? 'GET' : 'POST'),
    headers: { 'content-type': 'application/json', 'x-bizos-token': token },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data.detail ?? `HTTP ${r.status}`)
  return data as T
}
