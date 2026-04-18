import { useEffect, useRef, useState } from 'react'
import type { PollData, Status, Transcript } from '../types'

const POLL_INTERVAL = 250

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

  useEffect(() => {
    fetch('/mute-status')
      .then(r => r.json())
      .then(d => applyMute(d.muted))
      .catch(() => {})

    let timer: ReturnType<typeof setTimeout>

    const poll = async () => {
      try {
        const res  = await fetch(`/transcripts.json?t=${Date.now()}`)
        if (!res.ok) throw new Error('fetch failed')
        const data: PollData = await res.json()

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
      } catch {
        setStatus('offline')
      }
      timer = setTimeout(poll, POLL_INTERVAL)
    }

    poll()
    return () => clearTimeout(timer)
  }, [])

  return { transcripts, status, muted, partialAi, thinking, processing, toggleMute }
}
