import { useEffect, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Sidebar } from '@/components/Sidebar'
import { ChatView } from '@/components/ChatView'
import { ChatHeader } from '@/components/ChatHeader'
import { KnowledgeView } from '@/components/KnowledgeView'
import { SettingsDialog } from '@/components/SettingsDialog'
import { ArtifactPanel } from '@/components/ArtifactPanel'
import { ArtifactOpenHost } from '@/components/ArtifactOpenHost'
import { SidecarBanner } from '@/components/SidecarBanner'
import { reconcileContracts } from '@/artifacts/registry'
import { useConversations, useCreateConversation } from '@/hooks/useConversations'
import { useTasks, taskOfConversation } from '@/hooks/useTasks'

const LS_SIDEBAR = 'tender-agent.sidebar-collapsed'
const LS_ARTIFACTS = 'tender-agent.artifacts-collapsed'

export default function App() {
  const { data: conversations = [] } = useConversations()
  const { data: tasks = [] } = useTasks()
  const createConv = useCreateConversation()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 「新建会话」草稿页：主区展示欢迎页+输入框（convId=null），所属任务在输入框胶囊里选/建
  const [drafting, setDrafting] = useState(false)
  // 主区形态：chat=对话工作台 / kb=知识库（全局资料层，与任务无关）
  const [activeView, setActiveView] = useState<'chat' | 'kb'>('chat')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [pendingSend, setPendingSend] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(LS_SIDEBAR) === '1')
  const [artifactsCollapsed, setArtifactsCollapsed] = useState(() => localStorage.getItem(LS_ARTIFACTS) === '1')

  // 契约对账：sidecar 契约目录 vs 客户端 Processor 覆盖（缺失告警，防半接入状态）
  useEffect(() => {
    void reconcileContracts()
  }, [])

  // 进入时若已有会话而尚未选中，落到第一个（列表已按创建时间倒序）；草稿页期间不被抢占
  useEffect(() => {
    if (!drafting && !selectedId && conversations.length > 0) {
      setSelectedId(conversations[0].id)
    }
  }, [drafting, selectedId, conversations])

  // 首发消息：在所选任务下建会话 → 退出草稿选中它 → 把消息转给挂载后的 ChatView
  const handleRequestCreate = async (text: string, taskId: string) => {
    const conv = await createConv.mutateAsync(taskId)
    setDrafting(false)
    setSelectedId(conv.id)
    setPendingSend(text)
  }

  // 草稿页展示的会话 id（null=欢迎页）；进入草稿页时清空选中（高亮与任务胶囊保持一致），
  // 退出草稿 = 点任一会话（onSelect 会置回 drafting=false）
  const viewConvId = drafting ? null : selectedId
  const viewConv = viewConvId ? (conversations.find((c) => c.id === viewConvId) ?? null) : null
  const currentTask = viewConv ? taskOfConversation(tasks, conversations, viewConvId) : null

  return (
    <div className="app">
      <Sidebar
        selectedId={selectedId}
        onSelect={(id) => {
          setDrafting(false)
          setActiveView('chat')
          setSelectedId(id)
          setPendingSend(null)
        }}
        onNewSession={() => {
          setDrafting(true)
          setActiveView('chat')
          // 清掉旧会话高亮：草稿页里侧栏选中态与输入框任务胶囊指向一致，
          // 不再出现「侧栏亮着 A 任务的会话、胶囊却是 B 任务」的错位
          setSelectedId(null)
          setPendingSend(null)
        }}
        onOpenKnowledge={() => setActiveView('kb')}
        activeView={activeView}
        onOpenSettings={() => setSettingsOpen(true)}
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
        {activeView === 'kb' ? (
          <KnowledgeView />
        ) : (
          <>
            <ChatHeader task={currentTask} conversation={viewConv} />
            <ChatView
              key={viewConvId ?? 'root'}
              convId={viewConvId}
              onOpenArtifact={setPreviewId}
              initialSend={pendingSend}
              onRequestCreate={handleRequestCreate}
              onOpenSettings={() => setSettingsOpen(true)}
            />
          </>
        )}
      </main>
      {/* 产物面板是对话工作台的一部分：知识库视图下不渲染（grid auto 列自动收 0，卸载即停内部轮询） */}
      {activeView !== 'kb' && (
        <ArtifactPanel
          currentConvId={viewConvId}
          currentTask={currentTask}
          collapsed={artifactsCollapsed}
          onOpen={setPreviewId}
          onCollapse={() => {
            setArtifactsCollapsed((v) => {
              localStorage.setItem(LS_ARTIFACTS, v ? '0' : '1')
              return !v
            })
          }}
        />
      )}
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <ArtifactOpenHost artifactId={previewId} onClose={() => setPreviewId(null)} />
    </div>
  )
}
