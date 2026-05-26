interface Props { processing: boolean; thinking: boolean; partialAi: string }

export default function StatusRows({ processing, thinking, partialAi }: Props) {
  return (
    <>
      {processing && (
        <div className="flex items-center gap-3 py-4">
          <div className="w-9 h-9 rounded-lg bg-surface border border-white/[0.08] flex items-center justify-center font-mono text-[0.55rem] text-text3">YOU</div>
          <div className="flex gap-1.5 items-center">
            {[0, 0.15, 0.3].map(d => <span key={d} className="w-1.5 h-1.5 rounded-full bg-text3 animate-blink" style={{ animationDelay: `${d}s` }} />)}
          </div>
        </div>
      )}
      {thinking && !partialAi && (
        <div className="flex items-center gap-3 py-4">
          <div className="w-9 h-9 rounded-lg bg-purple/10 border border-purple/20 flex items-center justify-center font-mono text-[0.55rem] text-purple">AI</div>
          <div className="flex gap-1.5 items-center">
            {[0, 0.15, 0.3].map(d => <span key={d} className="w-1.5 h-1.5 rounded-full bg-purple animate-blinkSlow" style={{ animationDelay: `${d}s` }} />)}
          </div>
        </div>
      )}
      {partialAi && (
        <div className="flex gap-3 items-start py-4">
          <div className="w-9 h-9 rounded-lg bg-green/10 border border-green/20 flex items-center justify-center font-mono text-[0.55rem] text-green">AI</div>
          <div className="flex flex-col gap-1">
            <span className="font-mono text-[0.58rem] uppercase tracking-widest text-green/60">friday · streaming</span>
            <p className="text-text1 text-[0.92rem] leading-relaxed max-w-prose">
              {partialAi}<span className="inline-block w-0.5 h-4 bg-green ml-0.5 animate-blink align-middle" />
            </p>
          </div>
        </div>
      )}
    </>
  )
}
