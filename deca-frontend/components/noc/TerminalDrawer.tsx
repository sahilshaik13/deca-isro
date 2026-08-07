'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Plus, TerminalSquare, X } from 'lucide-react'
import XtermPane from '@/components/noc/XtermPane'
import {
  createTerminal,
  deleteTerminal,
  ensurePipeline,
  listTerminals,
  type FaultDemoStatus,
  type SimulationStatus,
  type TerminalSessionMeta,
  type TerminalTarget,
} from '@/lib/api'

const ADD_TARGETS: { id: TerminalTarget; label: string }[] = [
  { id: 'brain', label: 'brain (local)' },
  { id: 'station1', label: 'station1' },
  { id: 'station2', label: 'station2' },
  { id: 'station3', label: 'station3' },
]

const PIPELINE_IDS = [
  'm-pipe-inject',
  'm-pipe-telem',
  'm-pipe-infer',
  'm-pipe-copilot',
  'm-pipe-decide',
  'm-pipe-watch',
] as const

type Mode = 'pipeline' | 'shell'

type Props = {
  faultStatus?: FaultDemoStatus | null
  simulation?: SimulationStatus | null
  demoLive?: boolean
}

function isPipeline(t: TerminalSessionMeta) {
  return t.id.startsWith('m-pipe-') || t.target === 'pipeline'
}

export default function TerminalDrawer({
  faultStatus = null,
  simulation = null,
  demoLive = false,
}: Props) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>('pipeline')
  const [terminals, setTerminals] = useState<TerminalSessionMeta[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [visited, setVisited] = useState<Set<string>>(() => new Set())
  const [pickerOpen, setPickerOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const res = await listTerminals()
    const list = res?.terminals || []
    setTerminals(list)
    return list
  }, [])

  const ensureAndOpen = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      await ensurePipeline()
      const list = await refresh()
      setMode('pipeline')
      setOpen(true)
      const firstPipe = list.find((t) => t.id === 'm-pipe-inject') || list.find(isPipeline)
      if (firstPipe) setActiveId(firstPipe.id)
      // Pre-visit all pipeline panes so WS connects before fault click
      setVisited((prev) => {
        const next = new Set(prev)
        for (const id of PIPELINE_IDS) {
          if (list.some((t) => t.id === id)) next.add(id)
        }
        return next
      })
    } catch {
      setError('pipeline ensure failed')
    } finally {
      setBusy(false)
    }
  }, [refresh])

  useEffect(() => {
    if (faultStatus?.running || simulation?.running || demoLive) {
      void ensureAndOpen()
    }
  }, [faultStatus?.running, simulation?.running, demoLive, ensureAndOpen])

  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), 8000)
    return () => clearInterval(t)
  }, [refresh])

  const visible = useMemo(() => {
    if (mode === 'pipeline') {
      const pipes = terminals.filter(isPipeline)
      // Stable order matching guide tabs
      return PIPELINE_IDS.map((id) => pipes.find((t) => t.id === id)).filter(
        Boolean,
      ) as TerminalSessionMeta[]
    }
    return terminals.filter((t) => !isPipeline(t))
  }, [terminals, mode])

  useEffect(() => {
    if (!activeId || !visible.some((t) => t.id === activeId)) {
      setActiveId(visible[0]?.id ?? null)
    }
  }, [visible, activeId])

  useEffect(() => {
    if (!activeId) return
    setVisited((prev) => {
      if (prev.has(activeId)) return prev
      const next = new Set(prev)
      next.add(activeId)
      return next
    })
  }, [activeId])

  const onAdd = async (target: TerminalTarget) => {
    setBusy(true)
    setError(null)
    setPickerOpen(false)
    const res = await createTerminal(target)
    setBusy(false)
    if (!res?.ok || !res.terminal) {
      setError('Failed to open terminal (localhost only / limit reached?)')
      return
    }
    setMode('shell')
    await refresh()
    setActiveId(res.terminal.id)
    setOpen(true)
  }

  const onCloseTab = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setBusy(true)
    await deleteTerminal(id)
    setBusy(false)
    setVisited((prev) => {
      const next = new Set(prev)
      next.delete(id)
      return next
    })
    await refresh()
  }

  const active = visible.find((t) => t.id === activeId) || null

  return (
    <section className={`deca-term-drawer ${open ? 'is-open' : 'is-collapsed'}`}>
      <header className="deca-term-drawer-bar">
        <button
          type="button"
          className="deca-term-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <TerminalSquare size={14} />
          <span>Live demo log</span>
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>

        {open ? (
          <>
            <div className="deca-term-mode">
              <button
                type="button"
                className={mode === 'pipeline' ? 'deca-btn-primary' : 'deca-btn-ghost'}
                onClick={() => void ensureAndOpen()}
              >
                Pipeline
              </button>
              <button
                type="button"
                className={mode === 'shell' ? 'deca-btn-primary' : 'deca-btn-ghost'}
                onClick={() => setMode('shell')}
              >
                Shells
              </button>
            </div>
            <div className="deca-term-tabs" role="tablist">
              {visible.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={t.id === activeId}
                  className={`deca-term-tab ${t.id === activeId ? 'is-active' : ''} ${
                    t.readonly ? 'is-readonly' : 'is-interactive'
                  }`}
                  onClick={() => setActiveId(t.id)}
                  title={`${t.label} · ${t.mode} · ${t.status}${t.cmd_summary ? ` · ${t.cmd_summary}` : ''}`}
                >
                  <span className="deca-term-tab-label">{t.label}</span>
                  <span className="deca-term-tab-badge">
                    {isPipeline(t) ? 'live' : t.readonly ? 'ro' : 'rw'}
                  </span>
                  {t.mode === 'interactive' ? (
                    <span
                      className="deca-term-tab-close"
                      role="button"
                      tabIndex={0}
                      onClick={(e) => void onCloseTab(t.id, e)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          void deleteTerminal(t.id).then(() => refresh())
                        }
                      }}
                      aria-label={`Close ${t.label}`}
                    >
                      <X size={12} />
                    </span>
                  ) : null}
                </button>
              ))}
            </div>
          </>
        ) : null}

        <div className="deca-term-actions">
          {error ? <span className="deca-term-error">{error}</span> : null}
          {mode === 'pipeline' ? (
            <span className="deca-term-hint">
              Inject → predict timing (demo log)
            </span>
          ) : (
            <div className="deca-term-add-wrap">
              <button
                type="button"
                className="deca-btn-primary"
                disabled={busy}
                onClick={() => setPickerOpen((v) => !v)}
              >
                <Plus size={14} />
                Add Terminal
              </button>
              {pickerOpen ? (
                <div className="deca-term-picker" role="menu">
                  <p className="deca-term-picker-hint">Interactive shell target</p>
                  {ADD_TARGETS.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      className="deca-term-picker-item"
                      disabled={busy}
                      onClick={() => void onAdd(t.id)}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          )}
        </div>
      </header>

      {open ? (
        <div className="deca-term-body">
          {visible.length === 0 ? (
            <p className="deca-term-empty">
              {mode === 'pipeline'
                ? 'Pipeline sessions missing — is the backend running? Try Pipeline button.'
                : 'No shell sessions — Add Terminal or switch to Pipeline.'}
            </p>
          ) : (
            visible.map((t) =>
              visited.has(t.id) ? (
                <div
                  key={t.id}
                  className="deca-term-pane"
                  hidden={t.id !== activeId}
                  data-session={t.id}
                >
                  <XtermPane
                    sessionId={t.id}
                    readonly={t.readonly}
                    active={t.id === activeId}
                  />
                </div>
              ) : null,
            )
          )}
          {active ? (
            <footer className="deca-term-status">
              <span>
                {active.label} · {active.mode} · {active.status}
              </span>
              {active.cmd_summary ? <span className="deca-term-cmd">{active.cmd_summary}</span> : null}
            </footer>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
