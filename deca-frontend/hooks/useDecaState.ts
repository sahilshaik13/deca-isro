import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchDashboard } from '@/lib/api'
import { getPollIntervalMs } from '@/lib/env'
import type { DashboardResponse } from '@/lib/telemetry-context'

export function useDecaState() {
  const [decaState, setDecaState] = useState<DashboardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const hasData = useRef(false)

  const poll = useCallback(async () => {
    try {
      const result = await fetchDashboard()
      if (result) {
        hasData.current = true
        setDecaState(result)
        setError(null)
      } else if (!hasData.current) {
        // Only hard-error when we never got a successful payload.
        setError('DECA API unreachable — is uvicorn on :8000?')
      }
      // Transient blip: keep last good state, do not flash offline.
    } catch (err) {
      if (!hasData.current) {
        console.warn('DECA Engine offline:', err)
        setError('DECA API unreachable — is uvicorn on :8000?')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    poll()
    const interval = setInterval(poll, getPollIntervalMs())
    return () => clearInterval(interval)
  }, [poll])

  return { decaState, loading, error, refetch: poll }
}
