import { useEffect, useState } from 'react'

export const dataUrl = (path: string) => `${import.meta.env.BASE_URL}data/${path}`

export type DataStatus = 'loading' | 'live' | 'fallback'

export function useJson<T>(path: string, fallback: T): { data: T; status: DataStatus } {
  const [data, setData] = useState<T>(fallback)
  const [status, setStatus] = useState<DataStatus>('loading')

  useEffect(() => {
    let alive = true
    fetch(dataUrl(path), { cache: 'no-cache' })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((json) => {
        if (alive) { setData(json as T); setStatus('live') }
      })
      .catch(() => {
        if (alive) { setData(fallback); setStatus('fallback') }
      })
    return () => { alive = false }
  }, [path])

  return { data, status }
}
