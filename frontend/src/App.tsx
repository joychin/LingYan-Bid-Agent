import { useEffect, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Sidebar } from '@/components/Sidebar'
import { ChatView } from '@/components/ChatView'
import { SettingsDialog } from '@/components/SettingsDialog'
import { ArtifactPanel } from '@/components/ArtifactPanel'
import { ArtifactPreviewModal } from '@/components/ArtifactPreviewModal'
import { SidecarBanner } from '@/components/SidecarBanner'
import { useConversations, useCreateConversation } from '@/hooks/useConversations'

const LS_SIDEBAR = 'tender-agent.sidebar-collapsed'
const LS_ARTIFACTS = 'tender-agent.artifacts-collapsed'

export default function App() {
  const { data: conversations = [] } = useConversations()
  const createConv = useCreateConversation()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [pendingSend, setPendingSend] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(LS_SIDEBAR) === '1')
  const [artifactsCollapsed, setArtifactsCollapsed] = useState(() => localStorage.getItem(LS_ARTIFACTS) === '1')

  // 进入时若已有会话而尚未选中，落到第一个（列表已按创建时间倒序）
  useEffect(() => {
    if (!selectedId && conversations.length > 0) {
      setSelectedId(conversations[0].id)
    }
  }, [selectedId, conversations])

  // 无会话时的首发：创建会话 → 选中 → 把消息转给挂载后的 ChatView
  const handleRequestCreate = async (text: string) => {
    const conv = await createConv.mutateAsync()
    setSelectedId(conv.id)
    setPendingSend(text)
  }

  return (
    <div className="app">
      <Sidebar
        selectedId={selectedId}
        onSelect={(id) => {
          setSelectedId(id)
          setPendingSend(null)
        }}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenArtifacts={() => setArtifactsCollapsed(false)}
        collapsed={sidebarCollapsed}
        onCollapse={() => {
          setSidebarCollapsed((v) => {
            localStorage.setItem(LS_SIDEBAR, v ? '0' : '1')
            return !v
          })
        }}
      />
      <main className="main">
        <button
          type="button"
          className="side-toggle"
          title="展开侧栏"
          onClick={() => {
            setSidebarCollapsed(false)
            localStorage.setItem(LS_SIDEBAR, '0')
          }}
        >
          <ChevronRight />
        </button>
        <SidecarBanner />
        <ChatView
          key={selectedId ?? 'root'}
          convId={selectedId}
          onOpenArtifact={setPreviewId}
          initialSend={pendingSend}
          onRequestCreate={handleRequestCreate}
        />
      </main>
      <ArtifactPanel
        currentConvId={selectedId}
        collapsed={artifactsCollapsed}
        onOpen={setPreviewId}
        onCollapse={() => {
          setArtifactsCollapsed((v) => {
            localStorage.setItem(LS_ARTIFACTS, v ? '0' : '1')
            return !v
          })
        }}
      />
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <ArtifactPreviewModal artifactId={previewId} onClose={() => setPreviewId(null)} />
    </div>
  )
}
