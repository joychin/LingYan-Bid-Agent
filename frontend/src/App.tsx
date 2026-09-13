import { useCallback, useEffect, useRef, useState } from 'react'
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { Sidebar } from '@/components/Sidebar'
import { ChatView } from '@/components/ChatView'
import { ChatHeader } from '@/components/ChatHeader'
import { HomeView } from '@/components/HomeView'
import { KnowledgeView } from '@/components/KnowledgeView'
import { MaterialsLibraryView } from '@/components/MaterialsLibraryView'
import { TemplatesView } from '@/components/TemplatesView'
import { SettingsModal } from '@/components/SettingsModal'
import { ArtifactPanel } from '@/components/ArtifactPanel'
import { SidecarBanner } from '@/components/SidecarBanner'
import { ExitGuard } from '@/components/ExitGuard'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { reconcileContracts } from '@/artifacts/registry'
import { cn } from '@/lib/utils'
import { useConversations, useCreateConversation } from '@/hooks/useConversations'
import { useCreateTask, useTasks, taskOfConversation } from '@/hooks/useTasks'
import { useToast } from '@/context/Toast'
import type { DeliverableSignal } from '@/api/sse'

const LS_SIDEBAR = 'tender-agent.sidebar-collapsed'
const LS_ARTIFACTS = 'tender-agent.artifacts-collapsed'
const LS_THEME = 'tender-agent.theme'

export default function App() {
  const { data: conversations = [], isLoading: conversationsLoading } = useConversations()
  const { data: tasks = [], isLoading: tasksLoading } = useTasks()
  const createConv = useCreateConversation()
  const createTaskM = useCreateTask()
  const { toast } = useToast()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 「任务即房间」（2026-09-13）：会话只从任务内诞生——无会话选中时主区是任务首页
  // （HomeView），建任务在首页本页完成（卡内命名/整页拖放文件），不弹窗。
  // 建任务/首页拖放攒下的文件：任务/会话创建成功后交给挂载的 ChatView 走 FileUpload
  // 上传（转交模式同旧 initialSend：onSelect 导航时清空，ChatView 挂载后消费一次）
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  // 主区形态：chat=对话工作台 / kb=知识库（全局资料层，与任务无关）/
  // library=写作素材库（内容资产）/ templates=版式库（格式资产；2026-09-09 由「模板库」改名，标识符不动）
  const [activeView, setActiveView] = useState<'chat' | 'kb' | 'library' | 'templates'>('chat')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  // 工作台文件（work/ 的 md 过程产物）查看器当前打开的相对路径
  const [workbenchPath, setWorkbenchPath] = useState<string | null>(null)
  const [workbenchAnchor, setWorkbenchAnchor] = useState<number | null>(null)
  // 来源原件（sources/）预览当前打开的文件名（pdf/docx/图片，只读）
  const [sourceFile, setSourceFile] = useState<string | null>(null)
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

  // 工作区单槽的来源标记（交付物呈现守卫，2026-09-13）：user=用户手开（永不被
  // 自动呈现抢走——Canvas「自动打开被打扰」的社区抱怨教训）、auto=交付物自动
  // 打开（可被更新的交付物接力替换，同轮先目录后整本自然切换）、null=空闲。
  // 纯逻辑标记不驱动渲染：用 ref 而非 state，presentDeliverable 回调保持稳定
  // 引用（经 useRun 转发，失稳会连累 SSE 订阅 effect 重挂）。
  const slotOriginRef = useRef<'user' | 'auto' | null>(null)

  // 「本轮文件」chip 的打开动作：打开工作台文件查看器（清掉产物预览态，二者共用
  // 面板工作区）；面板收起时顺带展开（transient，不写 localStorage 偏好）。
  // useCallback 保引用稳定：MessageList/ChatMessage 是 memo 组件，回调换引用会破白名单。
  // anchorLine：来源追溯「查看原文上下文」定位（编辑器切源码栏滚到行）。
  // origin：单槽来源标记（自动呈现传 'auto'，用户点击缺省 'user'）。
  const openWorkbenchFile = useCallback((path: string, anchorLine?: number, origin: 'user' | 'auto' = 'user') => {
    slotOriginRef.current = origin
    setPreviewId(null)
    setSourceFile(null)
    setWorkbenchPath(path)
    setWorkbenchAnchor(anchorLine ?? null)
    setArtifactsCollapsed(false)
  }, [])
  // 与上面对称的单槽语义：打开产物时清掉工作台文件态，否则 workbenchPath 优先渲染、
  // 产物点击看似无响应（面板渲染是 workbenchPath ? WorkbenchViewer : ArtifactOpenHost）
  const openArtifact = useCallback((id: string, origin: 'user' | 'auto' = 'user') => {
    slotOriginRef.current = origin
    setWorkbenchPath(null)
    setSourceFile(null)
    setPreviewId(id)
    setArtifactsCollapsed(false)
  }, [])
  // 来源原件预览（sources/ 的 pdf/docx/图片，只读）：同一工作区单槽，互斥清理
  const openSourceFile = useCallback((name: string, origin: 'user' | 'auto' = 'user') => {
    slotOriginRef.current = origin
    setPreviewId(null)
    setWorkbenchPath(null)
    setWorkbenchAnchor(null)
    setSourceFile(name)
    setArtifactsCollapsed(false)
  }, [])

  // 交付物呈现（deliverable.created，产出即开）：面板空闲或正显示自动打开的内容
  // 才开——用户手开的文件/产物/原件永不被抢，chips/产物卡仍是手动出口；auto 内容
  // 可被更新的交付物接力替换。展开面板复用既有 transient 语义（不写收起偏好）。
  const presentDeliverable = useCallback(
    (d: DeliverableSignal) => {
      if (slotOriginRef.current === 'user') return
      if (d.kind === 'artifact' && d.artifactId) openArtifact(d.artifactId, 'auto')
      else if (d.kind === 'file' && d.path) openWorkbenchFile(d.path, undefined, 'auto')
    },
    [openArtifact, openWorkbenchFile],
  )

  // 契约对账：sidecar 契约目录 vs 客户端 Processor 覆盖（缺失告警，防半接入状态）
  useEffect(() => {
    void reconcileContracts()
  }, [])

  // 冷启动落任务首页（2026-09-13 拍板）：不再自动进入最新会话，「继续上次」一行即回

  // 建任务（首页卡内命名/整页拖放）：建任务（自带首个会话）→ 进入会话 → 文件转交
  // ChatView 上传。失败在此 toast（HomeView 无提示职责）
  const handleCreateTask = async (title: string, files: File[]) => {
    try {
      const body = await createTaskM.mutateAsync({ title, withConversation: true })
      // withConversation=true 应答必带会话；万一没有（后端行为变化）兜底补建一个
      const conv = body.conversation ?? (await createConv.mutateAsync(body.task.id))
      setSelectedId(conv.id)
      setPendingFiles(files)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  // 进入任务（首页卡片/继续上次）：优先打开其最近会话，无会话（历史遗留的空任务）就地建一个
  const handleOpenTask = async (taskId: string) => {
    const latest = conversations.find((c) => c.task_id === taskId)
    if (latest) {
      setSelectedId(latest.id)
      return
    }
    try {
      const conv = await createConv.mutateAsync(taskId)
      setSelectedId(conv.id)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  // 会话头部「＋ 新会话」：在当前任务内建会话并进入（与侧栏任务 hover「＋」同款语义）
  const handleNewConversationInTask = async (taskId: string) => {
    try {
      const conv = await createConv.mutateAsync(taskId)
      setSelectedId(conv.id)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  const viewConvId = selectedId
  const viewConv = viewConvId ? (conversations.find((c) => c.id === viewConvId) ?? null) : null
  const currentTask = viewConv ? taskOfConversation(tasks, conversations, viewConvId) : null

  return (
    <ErrorBoundary>
    <div className="app">
      <Sidebar
        selectedId={selectedId}
        onSelect={(id) => {
          setActiveView('chat')
          setSelectedId(id)
          // 建任务转交的文件由 ChatView 消费后回调清空（消费即清源，见 onInitialFilesConsumed）；
          // 这里导航时也清一次，兜住「消费前就导航走」的窗口（重复上传的二道防线）
          setPendingFiles([])
        }}
        onNewTask={() => {
          // 「新建任务」= 导航到任务首页（用户拍板，2026-09-13 验收）：建任务入口
          // （开始新投标卡/整页拖放）都在首页本页上，不弹窗
          setActiveView('chat')
          setSelectedId(null)
          setPendingFiles([])
        }}
        onOpenKnowledge={() => setActiveView('kb')}
        onOpenLibrary={() => setActiveView('library')}
        onOpenTemplates={() => setActiveView('templates')}
        activeView={activeView}
        onOpenSettings={() => setSettingsOpen(true)}
        theme={theme}
        onToggleTheme={toggleTheme}
        collapsed={sidebarCollapsed}
      />
      <main className="main">
        <SidecarBanner />
        {/* 退出拦截：还有任务在跑时关窗/cmd+Q 先弹确认（2026-09-12）；浏览器模式自禁用 */}
        <ExitGuard />
        {activeView === 'kb' ? (
          <KnowledgeView onGoLibrary={() => setActiveView('library')} />
        ) : activeView === 'library' ? (
          <MaterialsLibraryView />
        ) : activeView === 'templates' ? (
          <TemplatesView />
        ) : viewConvId ? (
          <>
            {/* viewConv 可能晚一拍（建会话后 conversations 失效重拉未回）：按选中 id
                分派而非 viewConv，避免先闪一下任务首页；头部短暂显示占位标题无碍 */}
            <ChatHeader
              task={currentTask}
              conversation={viewConv}
              onNewConversation={
                currentTask ? () => void handleNewConversationInTask(currentTask.id) : undefined
              }
            />
            <ChatView
              key={viewConvId}
              convId={viewConvId}
              onOpenArtifact={openArtifact}
              onOpenWorkbench={openWorkbenchFile}
              onPresentDeliverable={presentDeliverable}
              initialFiles={pendingFiles}
              onInitialFilesConsumed={() => setPendingFiles([])}
              onOpenSettings={() => setSettingsOpen(true)}
            />
          </>
        ) : (
          <HomeView
            onOpenTask={(taskId) => void handleOpenTask(taskId)}
            onCreateTask={handleCreateTask}
            onNewConversation={(taskId) => void handleNewConversationInTask(taskId)}
          />
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
          sourceFile={sourceFile}
          onOpen={openArtifact}
          onOpenWorkbench={openWorkbenchFile}
          onOpenSource={openSourceFile}
          onOpenLibrary={() => setActiveView('library')}
          onClearPreview={() => {
            slotOriginRef.current = null
            setPreviewId(null)
            setWorkbenchPath(null)
            setWorkbenchAnchor(null)
            setSourceFile(null)
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
