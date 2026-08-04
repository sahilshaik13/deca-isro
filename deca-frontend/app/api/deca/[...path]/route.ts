import { NextRequest, NextResponse } from 'next/server'

/** Prefer IPv4 loopback — Node often resolves `localhost` to ::1 while uvicorn binds 127.0.0.1. */
function resolveBackendUrl(): string {
  const raw = (
    process.env.DECA_API_URL ||
    process.env.NEXT_PUBLIC_DECA_API_URL ||
    'http://127.0.0.1:8000'
  ).replace(/\/$/, '')
  try {
    const u = new URL(raw)
    if (u.hostname === 'localhost') {
      u.hostname = '127.0.0.1'
    }
    return u.toString().replace(/\/$/, '')
  } catch {
    return 'http://127.0.0.1:8000'
  }
}

const backendUrl = resolveBackendUrl()

async function proxyOnce(
  url: string,
  method: string,
  headers: Record<string, string>,
  body: string | undefined,
  timeoutMs: number,
): Promise<Response> {
  return fetch(url, {
    method,
    headers,
    body,
    cache: 'no-store',
    signal: AbortSignal.timeout(timeoutMs),
  })
}

async function proxyRequest(request: NextRequest, pathSegments: string[]) {
  const targetPath = pathSegments.join('/')
  const url = `${backendUrl}/api/v1/${targetPath}${request.nextUrl.search}`

  const headers: Record<string, string> = { Accept: 'application/json' }
  const contentType = request.headers.get('content-type')
  if (contentType) {
    headers['Content-Type'] = contentType
  }

  const timeoutMs = targetPath === 'ask' ? 120_000 : 45_000
  const method = request.method
  const body =
    method !== 'GET' && method !== 'HEAD' ? await request.text() : undefined

  let lastError: unknown
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const response = await proxyOnce(url, method, headers, body, timeoutMs)
      const text = await response.text()
      return new NextResponse(text, {
        status: response.status,
        headers: {
          'Content-Type': response.headers.get('Content-Type') || 'application/json',
        },
      })
    } catch (error) {
      lastError = error
      if (attempt < 3) {
        await new Promise((r) => setTimeout(r, 300 * attempt))
        continue
      }
    }
  }

  const detail = lastError instanceof Error ? lastError.message : String(lastError)
  console.error(`DECA proxy failed (${url}):`, detail)
  return NextResponse.json(
    {
      success: false,
      error: 'DECA backend unreachable',
      detail,
      backend: backendUrl,
      hint: 'Start API: cd deca-backend && DECA_HEAVY_INIT=0 ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000',
    },
    { status: 503 },
  )
}

type RouteContext = { params: Promise<{ path: string[] }> }

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params
  return proxyRequest(request, path)
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params
  return proxyRequest(request, path)
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const { path } = await context.params
  return proxyRequest(request, path)
}
