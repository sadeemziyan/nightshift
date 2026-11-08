import { useEffect, useState } from 'react'
import * as api from './api'
import { mock } from './mock'

// Which screen is showing, kept in the URL hash so the phone page has its own address (#/jobs).
export function useHashRoute() {
  const read = () => (window.location.hash || '#/').replace(/^#\/?/, '') || 'console'
  const [route, setRoute] = useState(read)
  useEffect(() => {
    const onChange = () => setRoute(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

// The learned-normal series for one pump or pipeline sensor (GET /model/baseline).
// Falls back to a labeled sample when the backend or the model is not available.
export function useBaseline(assetId, metric, t, hours, usingMock) {
  const [result, setResult] = useState(null)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      let next
      try {
        if (usingMock) throw new Error('mock mode')
        next = { data: await api.getBaseline(assetId, metric, t, hours), source: 'live' }
      } catch {
        next = { data: mock.modelBaseline, source: 'mock' }
      }
      if (!cancelled) setResult(next)
    })()
    return () => {
      cancelled = true
    }
  }, [assetId, metric, t, hours, usingMock])
  return result
}

// Grey placeholder shown while something loads, so no screen is ever blank.
export const SKELETON = 'skeleton'
