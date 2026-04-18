import { useState } from 'react'
import { usePolling } from './hooks/usePolling'
import Header        from './components/Header'
import WaveformStrip from './components/WaveformStrip'
import ChatFeed      from './components/ChatFeed'
import PromptButtons from './components/PromptButtons'
import Footer        from './components/Footer'

export default function App() {
  const {
    transcripts, status, muted, partialAi,
    thinking, processing, toggleMute,
  } = usePolling()

  const [localList, setLocalList] = useState(transcripts)
  const displayList = transcripts.length ? transcripts : localList

  const exportChat = () => {
    const txt = displayList
      .map(e => `[${e.time}]\nYou: ${e.user}\nFriday: ${e.ai}`)
      .join('\n\n---\n\n')
    if (!txt) return
    const a    = document.createElement('a')
    a.href     = URL.createObjectURL(new Blob([txt], { type: 'text/plain' }))
    a.download = `friday-chat-${Date.now()}.txt`
    a.click()
  }

  const clearChat = () => setLocalList([])

  return (
    <div className="min-h-svh flex flex-col overflow-x-hidden bg-bg">
      <Header status={status} muted={muted} onToggleMute={toggleMute} />
      <WaveformStrip muted={muted} />
      <ChatFeed
        transcripts={displayList}
        processing={processing}
        thinking={thinking}
        partialAi={partialAi}
      />
      <PromptButtons />
      <Footer count={displayList.length} onExport={exportChat} onClear={clearChat} />
    </div>
  )
}
