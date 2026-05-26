import { Transcript } from '../types'

interface Props { entry: Transcript }

export default function MessageGroup({ entry }: Props) {
  return (
    <div className="py-7 border-b border-white/[0.06] last:border-0 flex flex-col gap-4 opacity-0 translate-y-2 animate-slidein">
      <div className="flex gap-3 items-start">
        <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-surface border border-white/[0.08] flex items-center justify-center font-mono text-[0.55rem] tracking-widest text-text2">YOU</div>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[0.58rem] uppercase tracking-widest text-text3">voice · translated</span>
          <p className="text-text1 text-[0.92rem] leading-relaxed max-w-prose">{entry.user}</p>
          <span className="font-mono text-[0.56rem] text-text3">{entry.time}</span>
        </div>
      </div>
      <div className="flex gap-3 items-start">
        <div className="flex-shrink-0 w-9 h-9 rounded-lg bg-green/10 border border-green/20 flex items-center justify-center font-mono text-[0.55rem] tracking-widest text-green">AI</div>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[0.58rem] uppercase tracking-widest text-green/60">friday</span>
          <p className="text-text1 text-[0.92rem] leading-relaxed max-w-prose">{entry.ai}</p>
        </div>
      </div>
    </div>
  )
}
