import { useEffect, useRef, useState } from 'react'
import type { PollData, Status, Transcript } from '../types'

// Server-Sent Events stream (with polling fallback if EventSource fails repeatedly).
const POLL_INTERVAL = 1000

export function usePolling() {
  const [transcripts, setTranscripts] = useState<Transcript[]>([])
  const [status, setStatus]           = useState<Status>('active')
  const [muted, setMuted]             = useState(false)
  const [partialAi, setPartialAi]     = useState('')
  const [thinking, setThinking]       = useState(false)
  const [processing, setProcessing]   = useState(false)
  const knownCount = useRef(0)

  const applyMute = (m: boolean) => {
    setMuted(m)
    if (m) setStatus('muted')
  }

  const toggleMute = async () => {
    try {
      const res  = await fetch('/toggle-mute', { method: 'POST' })
      const data = await res.json()
      applyMute(data.muted)
    } catch { /* ignore */ }
  }

  const ingest = (data: PollData) => {
    applyMute(!!data.muted)
    setProcessing(!!data.processing)
    setThinking(!!data.thinking)
    setPartialAi(data.partial_ai ?? '')

    if (!data.muted) {
      if (data.processing)                       setStatus('processing')
      else if (data.thinking || data.partial_ai) setStatus('thinking')
      else                                       setStatus('active')
    }

    const entries = data.transcripts ?? []
    if (entries.length > knownCount.current) {
      setTranscripts(entries)
      knownCount.current = entries.length
    }
  }

  useEffect(() => {
    fetch('/mute-status')
      .then(r => r.json())
      .then(d => applyMute(d.muted))
      .catch(() => {})

    let cancelled = false
    let pollTimer: ReturnType<typeof setTimeout> | null = null
    let es: EventSource | null = null

    const startPolling = () => {
      const tick = async () => {
        if (cancelled) return
        try {
          const res = await fetch(`/transcripts.json?t=${Date.now()}`)
          if (!res.ok) throw new Error('fetch failed')
          ingest(await res.json() as PollData)
        } catch {
          setStatus('offline')
        }
        pollTimer = setTimeout(tick, POLL_INTERVAL)
      }
      tick()
    }

    try {
      es = new EventSource('/events')
      es.onmessage = (e) => {
        try {
          ingest(JSON.parse(e.data) as PollData)
        } catch { /* ignore malformed frame */ }
      }
      es.onerror = () => {
        // EventSource auto-reconnects; if it stays down we'll show offline.
        if (es && es.readyState === EventSource.CLOSED) {
          setStatus('offline')
          es = null
          startPolling()
        }
      }
    } catch {
      startPolling()
    }

    return () => {
      cancelled = true
      if (pollTimer) clearTimeout(pollTimer)
      if (es) es.close()
    }
  }, [])

  return { transcripts, status, muted, partialAi, thinking, processing, toggleMute }
}
