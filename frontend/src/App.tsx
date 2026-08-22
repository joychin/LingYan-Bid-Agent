import { useEffect, useState } from 'react'
import { Sidebar } from '@/components/Sidebar'
import { ChatView } from '@/components/ChatView'
import { SettingsDialog } from '@/components/SettingsDialog'
import { useConversations } from '@/hooks/useConversations'

export default function App() {
  const { data: conversations = [] } = useConversations()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  // 进入时若无可选会话，落到第一个（列表已按创建时间倒序）
  useEffect(() => {
    if (!selectedId && conversations.length > 0) {
      setSelectedId(conversations[0].id)
    }
  }, [selectedId, conversations])

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      <Sidebar selectedId={selectedId} onSelect={setSelectedId} onOpenSettings={() => setSettingsOpen(true)} />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 items-center justify-between border-b px-4">
          <h1 className="text-sm font-semibold">Tender Agent</h1>
          <span className="text-xs text-muted-foreground">Local-first 标书助手</span>
        </header>
        {selectedId ? (
          <ChatView key={selectedId} convId={selectedId} />
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            新建一个会话开始
          </div>
        )}
      </main>
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
