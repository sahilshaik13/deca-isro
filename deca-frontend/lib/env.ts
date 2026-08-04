/** Same-origin proxy path (see next.config.mjs rewrites). */
export const DECA_API_PROXY_PATH = '/api/deca'

export function getApiBaseUrl(): string {
  // Browser: proxy through Next.js to avoid CORS and localhost/private-network blocks
  if (typeof window !== 'undefined') {
    return DECA_API_PROXY_PATH
  }

  const url = process.env.NEXT_PUBLIC_DECA_API_URL || 'http://localhost:8000'
  return url.replace(/\/$/, '')
}

/** Direct uvicorn base for WebSockets (Next JSON proxy cannot upgrade WS). */
export function getBackendHttpUrl(): string {
  const raw = (
    process.env.NEXT_PUBLIC_DECA_API_URL ||
    process.env.DECA_API_URL ||
    'http://127.0.0.1:8000'
  ).replace(/\/$/, '')
  try {
    const u = new URL(raw)
    if (u.hostname === 'localhost') u.hostname = '127.0.0.1'
    return u.toString().replace(/\/$/, '')
  } catch {
    return 'http://127.0.0.1:8000'
  }
}

export function getTerminalWsUrl(sessionId: string): string {
  const http = getBackendHttpUrl()
  const ws = http.replace(/^http/i, (m) => (m.toLowerCase() === 'https' ? 'wss' : 'ws'))
  return `${ws}/api/v1/terminals/${encodeURIComponent(sessionId)}/ws`
}

export function getPollIntervalMs(): number {
  const raw = process.env.NEXT_PUBLIC_DECA_POLL_MS
  const parsed = raw ? parseInt(raw, 10) : 5000
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 5000
}
