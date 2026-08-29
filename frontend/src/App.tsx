import { useEffect, useState } from 'react'
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { Sidebar } from '@/components/Sidebar'
import { ChatView } from '@/components/ChatView'
import { ChatHeader } from '@/components/ChatHeader'
import { KnowledgeView } from '@/components/KnowledgeView'
import { SettingsModal } from '@/components/SettingsModal'
import { ArtifactPanel } from '@/components/ArtifactPanel'
import { SidecarBanner } from '@/components/SidecarBanner'
import { ErrorBoundary } from '@/components/ErrorBoundary'
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
  // 工作台文件（out/ 的 md 过程产物）查看器当前打开的相对路径
  const [workbenchPath, setWorkbenchPath] = useState<string | null>(null)
  const [pendingSend, setPendingSend] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(LS_SIDEBAR) === '1')
  const [artifactsCollapsed, setArtifactsCollapsed] = useState(() => localStorage.getItem(LS_ARTIFACTS) === '1')

  // 左右面板开关（常驻中栏顶栏两端，见 ChatHeader）：开关全局只此一处
  const toggleSidebar = () =>
    setSidebarCollapsed((v) => {
      localStorage.setItem(LS_SIDEBAR, v ? '0' : '1')
      return !v
    })
  const toggleArtifacts = () =>
    setArtifactsCollapsed((v) => {
      localStorage.setItem(LS_ARTIFACTS, v ? '0' : '1')
      return !v
    })

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
    <ErrorBoundary>
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
      />
      <main className="main">
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
      {/* 产物面板是对话工作台的一部分：知识库视图/无会话上下文（草稿态）不渲染
          （grid auto 列自动收 0，卸载即停内部轮询）。
          v3：previewId/workbenchPath 驱动面板工作区态，编辑器嵌入面板右侧（覆盖展开），
          不再用居中模态。 */}
      {activeView !== 'kb' && currentTask && (
        <ArtifactPanel
          currentConvId={viewConvId}
          currentTask={currentTask}
          collapsed={artifactsCollapsed}
          previewId={previewId}
          workbenchPath={workbenchPath}
          onOpen={setPreviewId}
          onOpenWorkbench={setWorkbenchPath}
          onClearPreview={() => {
            setPreviewId(null)
            setWorkbenchPath(null)
          }}
        />
      )}
      {/* 左右面板固定开关（用户定稿 2026-08-29，对齐 ZCode 手感）：钉在窗口顶角，
          位置不随面板开合变化，面板从其下方滑入滑出，按钮只换图标（图标即状态）。
          z 40 浮于两侧面板头之上、低于模态 z-50 */}
      <button
        type="button"
        className="head-toggle pin-left"
        title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}
        onClick={toggleSidebar}
      >
        {sidebarCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
      </button>
      {activeView !== 'kb' && currentTask && (
        <button
          type="button"
          className="head-toggle pin-right"
          title={artifactsCollapsed ? '展开产物面板' : '收起产物面板'}
          onClick={toggleArtifacts}
        >
          {artifactsCollapsed ? <PanelRightOpen /> : <PanelRightClose />}
        </button>
      )}
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
    </ErrorBoundary>
  )
}
