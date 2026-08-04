'use client'

import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Plus, TerminalSquare, X } from 'lucide-react'
import XtermPane from '@/components/noc/XtermPane'
import {
  createTerminal,
  deleteTerminal,
  listTerminals,
  type TerminalSessionMeta,
  type TerminalTarget,
} from '@/lib/api'

const ADD_TARGETS: { id: TerminalTarget; label: string }[] = [
  { id: 'brain', label: 'brain (local)' },
  { id: 'station1', label: 'station1' },
  { id: 'station2', label: 'station2' },
  { id: 'station3', label: 'station3' },
]

export default function TerminalDrawer() {
  const [open, setOpen] = useState(false)
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
    setActiveId((prev) => {
      if (prev && list.some((t) => t.id === prev)) return prev
      return list[0]?.id ?? null
    })
  }, [])

  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), 8000)
    return () => clearInterval(t)
  }, [refresh])

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

  const active = terminals.find((t) => t.id === activeId) || null

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
          <span>Terminals</span>
          {open ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>

        {open ? (
          <div className="deca-term-tabs" role="tablist">
            {terminals.map((t) => (
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
                  {t.readonly ? 'ro' : 'rw'} · {t.target}
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
        ) : null}

        <div className="deca-term-actions">
          {error ? <span className="deca-term-error">{error}</span> : null}
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
        </div>
      </header>

      {open ? (
        <div className="deca-term-body">
          {terminals.length === 0 ? (
            <p className="deca-term-empty">No terminal sessions yet — is the backend running?</p>
          ) : (
            terminals.map((t) =>
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
