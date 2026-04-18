import { Status } from '../types'

interface Props { status: Status; muted: boolean; onToggleMute: () => void }

const DOT_CLASS: Record<Status, string> = {
  active:     'bg-green shadow-[0_0_10px_#00f5a0] animate-pulse2',
  processing: 'bg-amber shadow-[0_0_10px_#ffc94a] animate-blink',
  thinking:   'bg-purple shadow-[0_0_10px_#9b7fff] animate-blinkSlow',
  muted:      'bg-red shadow-[0_0_10px_#ff4f6e]',
  offline:    'bg-text3',
}

const STATUS_LABEL: Record<Status, string> = {
  active: 'listening', processing: 'transcribing',
  thinking: 'thinking', muted: 'muted', offline: 'offline',
}

const STATUS_COLOR: Record<Status, string> = {
  active: 'text-green', processing: 'text-amber',
  thinking: 'text-purple', muted: 'text-red', offline: 'text-text3',
}

export default function Header({ status, muted, onToggleMute }: Props) {
  const isListening = !muted && status === 'active'
  return (
    <header className="fixed top-0 inset-x-0 z-50 h-[60px] flex items-center justify-between px-6 bg-bg/85 backdrop-blur-xl border-b border-white/[0.06]">
      <div className="flex items-center gap-2.5 font-mono text-[0.95rem] tracking-[0.04em]">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 transition-all duration-300 ${DOT_CLASS[muted ? 'muted' : status]}`} />
        <span className="text-text1">fri<em className="not-italic text-green">day</em></span>
      </div>
      <div className="absolute left-1/2 -translate-x-1/2">
        <span className={`font-mono text-[0.6rem] tracking-[0.1em] uppercase px-2.5 py-1 rounded-full border transition-all duration-300 ${isListening ? 'border-green/30 text-green bg-green/10' : 'border-white/10 text-text2 bg-surface'}`}>
          {isListening ? '* listening' : 'hey friday'}
        </span>
      </div>
      <div className="flex items-center gap-2.5">
        <span className="hidden sm:block font-mono text-[0.58rem] tracking-[0.08em] uppercase text-text3 px-2 py-0.5 border border-white/[0.06] rounded">
          <span className={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</span>
        </span>
        <button onClick={onToggleMute}
          className={`flex items-center gap-2 font-mono text-[0.62rem] tracking-[0.08em] uppercase px-3.5 py-1.5 rounded-md border transition-all duration-200 ${muted ? 'border-red/30 bg-red/10 text-red hover:bg-red/20' : 'border-green/30 bg-green/10 text-green hover:bg-green/20 hover:border-green/50'}`}>
          {muted ? '[muted]' : '[live]'}
          {muted ? 'mic off' : 'mic on'}
        </button>
      </div>
    </header>
  )
}
