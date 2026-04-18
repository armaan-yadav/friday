import { useState } from 'react'

const PREDEFINED_PROMPTS = [
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

export default function PromptButtons() {
  const [loading, setLoading] = useState(false)
  const [showAll, setShowAll] = useState(false)

  const sendPrompt = async (prompt: string) => {
    setLoading(true)
    console.log('[PromptButtons] Sending prompt:', prompt)
    try {
      const response = await fetch('/send-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      console.log('[PromptButtons] Response status:', response.status)
      if (!response.ok) {
        const errorText = await response.text()
        console.error('Failed to send prompt:', response.status, errorText)
      } else {
        const data = await response.json()
        console.log('[PromptButtons] Success:', data)
      }
    } catch (error) {
      console.error('Error sending prompt:', error)
    } finally {
      setLoading(false)
    }
  }

  const displayPrompts = showAll ? PREDEFINED_PROMPTS : PREDEFINED_PROMPTS.slice(0, 3)

  return (
    <div className="fixed bottom-14 inset-x-0 z-40 flex flex-col gap-2 px-6 py-3 bg-bg/70 backdrop-blur-sm border-t border-white/[0.06]">
      <div className="flex flex-wrap gap-2 justify-center">
        {displayPrompts.map((prompt) => (
          <button
            key={prompt}
            onClick={() => sendPrompt(prompt)}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded border border-white/[0.12] bg-white/[0.03] text-text2 hover:text-text1 hover:border-white/20 hover:bg-white/[0.06] transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed truncate"
            title={prompt}
          >
            {prompt}
          </button>
        ))}
      </div>
      
      {!showAll && PREDEFINED_PROMPTS.length > 3 && (
        <button
          onClick={() => setShowAll(true)}
          className="text-[0.65rem] px-3 py-1 text-text3 hover:text-text2 transition-colors duration-150 mx-auto"
        >
          show more
        </button>
      )}
      
      {showAll && (
        <button
          onClick={() => setShowAll(false)}
          className="text-[0.65rem] px-3 py-1 text-text3 hover:text-text2 transition-colors duration-150 mx-auto"
        >
          show less
        </button>
      )}
    </div>
  )
}
