import { useCallback, useEffect, useRef, useState } from 'react'
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { Sidebar } from '@/components/Sidebar'
import { ChatView } from '@/components/ChatView'
import { ChatHeader } from '@/components/ChatHeader'
import { KnowledgeView } from '@/components/KnowledgeView'
import { MaterialsLibraryView } from '@/components/MaterialsLibraryView'
import { SettingsModal } from '@/components/SettingsModal'
import { ArtifactPanel } from '@/components/ArtifactPanel'
import { SidecarBanner } from '@/components/SidecarBanner'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { reconcileContracts } from '@/artifacts/registry'
import { cn } from '@/lib/utils'
import { useConversations, useCreateConversation } from '@/hooks/useConversations'
import { useTasks, taskOfConversation } from '@/hooks/useTasks'

const LS_SIDEBAR = 'tender-agent.sidebar-collapsed'
const LS_ARTIFACTS = 'tender-agent.artifacts-collapsed'
const LS_THEME = 'tender-agent.theme'

export default function App() {
  const { data: conversations = [], isLoading: conversationsLoading } = useConversations()
  const { data: tasks = [], isLoading: tasksLoading } = useTasks()
  const createConv = useCreateConversation()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 「新建会话」草稿页：主区展示欢迎页+输入框（convId=null），所属任务在输入框胶囊里选/建
  const [drafting, setDrafting] = useState(false)
  // 主区形态：chat=对话工作台 / kb=知识库（全局资料层，与任务无关）
  const [activeView, setActiveView] = useState<'chat' | 'kb' | 'library'>('chat')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  // 工作台文件（work/ 的 md 过程产物）查看器当前打开的相对路径
  const [workbenchPath, setWorkbenchPath] = useState<string | null>(null)
  const [workbenchAnchor, setWorkbenchAnchor] = useState<number | null>(null)
  const [pendingSend, setPendingSend] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(LS_SIDEBAR) === '1')
  const [artifactsCollapsed, setArtifactsCollapsed] = useState(() => localStorage.getItem(LS_ARTIFACTS) === '1')
  // 主题：首帧由 main.tsx 写 documentElement（localStorage 优先，否则跟随系统），这里只同步 React 态驱动图标
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
  )

  // 左右面板开关（常驻中栏顶栏两端，见 ChatHeader）：开关全局只此一处
  const toggleSidebar = () =>
    setSidebarCollapsed((v) => {
      localStorage.setItem(LS_SIDEBAR, v ? '0' : '1')
      return !v
    })
  const themeGuard = useRef<number | undefined>(undefined)
  // 主题切换：翻转瞬间挂 theme-switching 类全局禁用过渡——.chat-item 选中高亮等带
  // background transition 的元素若照常补间，暗色翻转瞬间会残留一块旧主题亮色，特别晃眼；
  // 100ms 后摘类，hover 淡入等微交互不受影响（连点时 clearTimeout 重置窗口）
  const toggleTheme = () => {
    const root = document.documentElement
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem(LS_THEME, next)
    root.classList.add('theme-switching')
    root.dataset.theme = next
    window.clearTimeout(themeGuard.current)
    themeGuard.current = window.setTimeout(() => root.classList.remove('theme-switching'), 100)
    setTheme(next)
  }
  const toggleArtifacts = () =>
    setArtifactsCollapsed((v) => {
      localStorage.setItem(LS_ARTIFACTS, v ? '0' : '1')
      return !v
    })

  // 「本轮文件」chip 的打开动作：打开工作台文件查看器（清掉产物预览态，二者共用
  // 面板工作区）；面板收起时顺带展开（transient，不写 localStorage 偏好）。
  // useCallback 保引用稳定：MessageList/ChatMessage 是 memo 组件，回调换引用会破白名单。
  // anchorLine：来源追溯「查看原文上下文」定位（编辑器切源码栏滚到行）。
  const openWorkbenchFile = useCallback((path: string, anchorLine?: number) => {
    setPreviewId(null)
    setWorkbenchPath(path)
    setWorkbenchAnchor(anchorLine ?? null)
    setArtifactsCollapsed(false)
  }, [])
  // 与上面对称的单槽语义：打开产物时清掉工作台文件态，否则 workbenchPath 优先渲染、
  // 产物点击看似无响应（面板渲染是 workbenchPath ? WorkbenchViewer : ArtifactOpenHost）
  const openArtifact = useCallback((id: string) => {
    setWorkbenchPath(null)
    setPreviewId(id)
    setArtifactsCollapsed(false)
  }, [])

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
        onOpenLibrary={() => setActiveView('library')}
        activeView={activeView}
        onOpenSettings={() => setSettingsOpen(true)}
        theme={theme}
        onToggleTheme={toggleTheme}
        collapsed={sidebarCollapsed}
      />
      <main className="main">
        <SidecarBanner />
        {activeView === 'kb' ? (
          <KnowledgeView />
        ) : activeView === 'library' ? (
          <MaterialsLibraryView />
        ) : (
          <>
            <ChatHeader task={currentTask} conversation={viewConv} />
            <ChatView
              key={viewConvId ?? 'root'}
              convId={viewConvId}
              onOpenArtifact={openArtifact}
              onOpenWorkbench={openWorkbenchFile}
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
      {/* 面板列宽预留（CLS）：会话已选而 tasks/conversations 仍在加载时先占住同宽
          槽位，任务数据到达后面板原地出现——聊天列不再被迟到的 300px 挤窄整列
          重折行（一次大位移的主因之一）；加载完确无所属任务则不占位。
          collapsed 偏好同步应用（收起态槽位宽度 0，与真实面板同宽）。 */}
      {activeView === 'chat' && viewConvId && !currentTask && (conversationsLoading || tasksLoading) && (
        <div className={cn('ap-slot', artifactsCollapsed && 'collapsed')} aria-hidden />
      )}
      {activeView === 'chat' && currentTask && (
        <ArtifactPanel
          currentConvId={viewConvId}
          currentTask={currentTask}
          collapsed={artifactsCollapsed}
          previewId={previewId}
          workbenchPath={workbenchPath}
          workbenchAnchor={workbenchAnchor}
          onOpen={openArtifact}
          onOpenWorkbench={openWorkbenchFile}
          onClearPreview={() => {
            setPreviewId(null)
            setWorkbenchPath(null)
            setWorkbenchAnchor(null)
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
      {activeView === 'chat' && currentTask && (
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
