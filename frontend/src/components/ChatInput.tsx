import { useRef, useState, KeyboardEvent, ChangeEvent } from 'react'

const SUGGESTIONS = [
  "What is the weather today?",
  "Tell me the latest news",
  "What time is it?",
  "How are you?",
  "Tell me a joke",
  "What's 2 + 2?",
  "Play some music",
  "What's the news on Iran-Israel war?",
  "What are the top stories?",
  "Set a reminder",
]

async function postPrompt(prompt: string): Promise<void> {
  const trimmed = prompt.trim()
  if (!trimmed) return
  try {
    const res = await fetch('/send-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: trimmed }),
    })
    if (!res.ok) {
      const err = await res.text()
      console.error('[ChatInput] /send-prompt failed:', res.status, err)
    }
  } catch (err) {
    console.error('[ChatInput] network error:', err)
  }
}

export default function ChatInput() {
  const [text, setText] = useState('')
  const [showAll, setShowAll] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const visibleSuggestions = showAll ? SUGGESTIONS : SUGGESTIONS.slice(0, 3)
  const canSend = text.trim().length > 0

  const resize = () => {
    const el = taRef.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }

  const onChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    resize()
  }

  const submit = () => {
    if (!canSend) return
    const value = text
    setText('')
    queueMicrotask(resize)
    void postPrompt(value)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const sendSuggestion = (s: string) => {
    void postPrompt(s)
  }

  return (
    <div className="fixed bottom-14 inset-x-0 z-40 bg-bg/85 backdrop-blur-xl border-t border-white/[0.06]">
      <div className="max-w-[760px] mx-auto px-4 pt-2.5 pb-3 flex flex-col gap-2">
        <div className="flex flex-wrap gap-1.5 justify-center">
          {visibleSuggestions.map(s => (
            <button
              key={s}
              onClick={() => sendSuggestion(s)}
              className="text-[0.7rem] px-2.5 py-1 rounded-full border border-white/[0.08] bg-white/[0.02] text-text2 hover:text-text1 hover:border-white/[0.18] hover:bg-white/[0.05] transition-all duration-150 truncate max-w-[220px]"
              title={s}
            >
              {s}
            </button>
          ))}
          {SUGGESTIONS.length > 3 && (
            <button
              onClick={() => setShowAll(v => !v)}
              className="text-[0.62rem] font-mono uppercase tracking-widest px-2 py-1 text-text3 hover:text-text2 transition-colors duration-150"
            >
              {showAll ? 'less' : 'more'}
            </button>
          )}
        </div>

        <form
          onSubmit={e => { e.preventDefault(); submit() }}
          className="flex items-end gap-2 rounded-2xl border border-white/[0.08] bg-surface/80 backdrop-blur-xl px-3 py-2 focus-within:border-green/40 focus-within:shadow-[0_0_0_3px_rgba(0,245,160,0.08)] transition-all duration-150"
        >
          <textarea
            ref={taRef}
            value={text}
            onChange={onChange}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Message Friday — or say 'hey friday'"
            className="flex-1 resize-none bg-transparent outline-none text-text1 placeholder:text-text3 text-sm leading-6 max-h-[120px]"
          />
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Send"
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-xl bg-green/15 text-green border border-green/25 hover:bg-green/25 hover:border-green/45 transition-all duration-150 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-green/15 disabled:hover:border-green/25"
          >
            <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4" aria-hidden="true">
              <path d="M10 16V4M10 4l-5 5M10 4l5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  )
}
