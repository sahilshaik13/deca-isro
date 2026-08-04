'use client'

import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { getTerminalWsUrl } from '@/lib/env'
import '@xterm/xterm/css/xterm.css'

export default function XtermPane({
  sessionId,
  readonly,
  active,
}: {
  sessionId: string
  readonly: boolean
  active: boolean
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!hostRef.current) return

    const term = new Terminal({
      cursorBlink: !readonly,
      disableStdin: readonly,
      convertEol: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      fontSize: 12,
      theme: {
        background: '#070b10',
        foreground: '#d6e0ea',
        cursor: readonly ? '#070b10' : '#c9a227',
        selectionBackground: '#2a3a4a',
      },
      scrollback: 4000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.loadAddon(new WebLinksAddon())
    term.open(hostRef.current)
    fit.fit()
    termRef.current = term
    fitRef.current = fit

    if (readonly) {
      term.writeln('\x1b[90m[read-only monitor — input disabled]\x1b[0m')
    }

    const ws = new WebSocket(getTerminalWsUrl(sessionId))
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      const dims = { type: 'resize', rows: term.rows, cols: term.cols }
      ws.send(JSON.stringify(dims))
    }

    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        term.write(ev.data)
        return
      }
      term.write(new Uint8Array(ev.data as ArrayBuffer))
    }

    ws.onerror = () => {
      term.writeln('\r\n\x1b[31m[ws error]\x1b[0m')
    }

    ws.onclose = () => {
      term.writeln('\r\n\x1b[90m[disconnected]\x1b[0m')
    }

    const onData = term.onData((data) => {
      if (readonly) return
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    const onResize = term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', rows, cols }))
      }
    })

    const ro = new ResizeObserver(() => {
      try {
        fit.fit()
      } catch {
        /* ignore */
      }
    })
    ro.observe(hostRef.current)

    return () => {
      onData.dispose()
      onResize.dispose()
      ro.disconnect()
      try {
        ws.close()
      } catch {
        /* ignore */
      }
      term.dispose()
      termRef.current = null
      fitRef.current = null
      wsRef.current = null
    }
  }, [sessionId, readonly])

  useEffect(() => {
    if (!active) return
    const id = requestAnimationFrame(() => {
      try {
        fitRef.current?.fit()
        termRef.current?.focus()
      } catch {
        /* ignore */
      }
    })
    return () => cancelAnimationFrame(id)
  }, [active])

  return <div ref={hostRef} className="deca-xterm-host" data-active={active ? '1' : '0'} />
}
