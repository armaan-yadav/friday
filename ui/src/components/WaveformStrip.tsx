import { useRef, useEffect } from 'react'
import { useMicVisualizer } from '../hooks/useMicVisualizer'

const BAR_COUNT = 100

interface Props { muted: boolean }

export default function WaveformStrip({ muted }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const barsRef = useMicVisualizer(muted)

  useEffect(() => {
    if (!containerRef.current) return
    barsRef.current = Array.from(containerRef.current.querySelectorAll<HTMLDivElement>('.bar'))
  }, [barsRef])

  return (
    <div className="fixed top-[60px] inset-x-0 z-40 h-9 flex items-center gap-[1.5px] px-5 bg-bg/70 backdrop-blur-md border-b border-white/[0.06] overflow-hidden">
      <div ref={containerRef} className="flex items-center gap-[1.5px] w-full h-full">
        {Array.from({ length: BAR_COUNT }).map((_, i) => (
          <div key={i} className="bar flex-1 min-w-[2px] bg-green rounded-[1px]"
               style={{ height: '2px', opacity: 0.1, transition: 'height 0.04s, opacity 0.04s' }} />
        ))}
      </div>
    </div>
  )
}
