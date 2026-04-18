import { useEffect, useRef } from 'react'
import { Transcript } from '../types'
import MessageGroup from './MessageGroup'
import StatusRows from './StatusRows'

interface Props { transcripts: Transcript[]; processing: boolean; thinking: boolean; partialAi: string }

export default function ChatFeed({ transcripts, processing, thinking, partialAi }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcripts.length, partialAi])

  const isEmpty = transcripts.length === 0 && !processing && !thinking && !partialAi

  return (
    <main className="relative z-10 flex-1 pt-[110px] pb-40 max-w-[760px] w-full mx-auto px-5 flex flex-col">
      {isEmpty ? (
        <div className="flex flex-col items-center justify-center flex-1 min-h-[50vh] gap-5 text-center">
          <div className="w-24 h-24 rounded-full bg-[radial-gradient(circle_at_40%_35%,rgba(0,245,160,0.15),rgba(155,127,255,0.08)_60%,transparent_80%)] border border-green/15 flex items-center justify-center">
            <span className="font-mono text-green text-2xl">MIC</span>
          </div>
          <p className="text-text2 text-sm font-medium tracking-wide">Waiting for you to speak</p>
          <p className="font-mono text-[0.65rem] uppercase tracking-[0.1em] text-text3">hey friday · wake word</p>
        </div>
      ) : (
        <>
          {transcripts.map(t => <MessageGroup key={t.timestamp} entry={t} />)}
          <StatusRows processing={processing} thinking={thinking} partialAi={partialAi} />
        </>
      )}
      <div ref={bottomRef} />
    </main>
  )
}
