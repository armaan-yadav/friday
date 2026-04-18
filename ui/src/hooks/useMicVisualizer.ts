import { useEffect, useRef } from 'react'

export function useMicVisualizer(muted: boolean) {
  const barsRef = useRef<HTMLDivElement[]>([])

  useEffect(() => {
    let rafId: number
    let analyser: AnalyserNode | null = null
    let data: Uint8Array

    const draw = (t = 0) => {
      rafId = requestAnimationFrame(() => draw(t + 0.025))
      if (muted) {
        barsRef.current.forEach(b => { b.style.height = '2px'; b.style.opacity = '0.04' })
        return
      }
      if (analyser) {
        analyser.getByteFrequencyData(data as any)
        barsRef.current.forEach((b, i) => {
          const bin = Math.floor((i / barsRef.current.length) * data.length)
          const v   = data[bin]
          b.style.height     = `${2 + (v / 255) * 28}px`
          b.style.opacity    = `${0.08 + (v / 255) * 0.85}`
          b.style.background = `rgb(0,${Math.floor(245 - (v / 255) * 80)},160)`
        })
      } else {
        barsRef.current.forEach((b, i) => {
          const h = 2 + Math.abs(Math.sin(t + i * 0.18)) * 7
          b.style.height     = `${h}px`
          b.style.opacity    = `${0.05 + Math.abs(Math.sin(t + i * 0.14)) * 0.05}`
          b.style.background = '#00f5a0'
        })
      }
    }

    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        const ctx = new AudioContext()
        const src = ctx.createMediaStreamSource(stream)
        analyser  = ctx.createAnalyser()
        analyser.fftSize = 256
        src.connect(analyser)
        data = new Uint8Array(analyser.frequencyBinCount)
        draw()
      })
      .catch(() => draw())

    return () => cancelAnimationFrame(rafId)
  }, [muted])

  return barsRef
}
