import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  BookOpen,
  Folder,
  FolderOpen,
  MoreHorizontal,
  Package,
  PanelLeftClose,
  Pencil,
  Plus,
  Settings,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useRenameConversation,
} from '@/hooks/useConversations'
import { useDeleteTask, useRenameTask, useTasks } from '@/hooks/useTasks'
import { useSidecarHealth } from '@/context/SidecarHealth'
import { useFileUpload } from '@/context/FileUpload'
import { useToast } from '@/context/Toast'
import { useKbBadge } from '@/hooks/useKnowledge'
import { cn, formatRelativeTime } from '@/lib/utils'
import type { Conversation, Task } from '@/api/client'
import { ChatItem } from '@/components/workspace/ChatItem'
import { NavRow } from '@/components/workspace/NavRow'
import { NavSection } from '@/components/workspace/NavSection'
import { UserBar } from '@/components/workspace/UserBar'

export interface SidebarProps {
  selectedId: string | null
  onSelect: (id: string | null) => void
  /** 「新建任务」：进入新建会话草稿页（所属任务在输入框胶囊里选/建） */
  onNewSession: () => void
  /** 打开知识库视图（全局资料层） */
  onOpenKnowledge: () => void
  /** 主区形态：决定知识库入口的 active 态 */
  activeView?: 'chat' | 'kb'
  onOpenSettings: () => void
  collapsed: boolean
  onCollapse: () => void
}

const SIDE_DEFAULT_W = 264
const SIDE_MIN_W = 200
const SIDE_MAX_W = 400

const STATUS_DOT: Record<string, string> = {
  ok: 'bg-success',
  reconnecting: 'bg-warning',
  failed: 'bg-error',
}
const STATUS_LABEL: Record<string, string> = {
  ok: '正常',
  reconnecting: '重连中',
  failed: '失败',
}

/** AbortSignal 超时的原始 message 是 "signal timed out"，对用户不可读 */
function errMsg(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e)
  return m === 'signal timed out' ? '请求超时，请重试' : m
}

/** Workspace 侧栏：快捷导航 + 「任务」分区（任务文件夹 → 会话两级）+ 用户栏。 */
export function Sidebar({
  selectedId,
  onSelect,
  onNewSession,
  onOpenKnowledge,
  activeView = 'chat',
  onOpenSettings,
  collapsed,
  onCollapse,
}: SidebarProps) {
  const { data: conversations = [], isLoading } = useConversations()
  const { data: tasks = [] } = useTasks()
  const createConv = useCreateConversation()
  const renameConv = useRenameConversation()
  const deleteConv = useDeleteConversation()
  const renameTask = useRenameTask()
  const deleteTaskM = useDeleteTask()
  const { status: sidecarStatus } = useSidecarHealth()
  const { setTaskScope } = useFileUpload()
  const { toast } = useToast()
  const kbBadge = useKbBadge()
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [taskMenuFor, setTaskMenuFor] = useState<string | null>(null)
  const [renamingTask, setRenamingTask] = useState<Task | null>(null)
  const [taskRenameValue, setTaskRenameValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<Conversation | null>(null)
  const [confirmDeleteTask, setConfirmDeleteTask] = useState<Task | null>(null)
  // 确认弹窗内联错误：删除失败时弹窗保持打开、红字展示原因，可重试（不再静默关闭）
  const [confirmError, setConfirmError] = useState<string | null>(null)
  // 拖拽调宽（照 ArtifactPanel 的 resizer 模式；宽度 = 鼠标 x − app 左缘）
  const [width, setWidth] = useState(SIDE_DEFAULT_W)
  const [dragging, setDragging] = useState(false)
  const appRect = useRef<DOMRect | null>(null)

  // 点击菜单外部区域时收起「···」菜单（会话与任务菜单共用）
  useEffect(() => {
    if (!menuFor && !taskMenuFor) return
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node | null
      if (target && !(target as HTMLElement).closest?.('[data-menu]')) {
        setMenuFor(null)
        setTaskMenuFor(null)
      }
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [menuFor, taskMenuFor])

  const handleNewConv = async (taskId: string) => {
    if (createConv.isPending) return
    try {
      const conv = await createConv.mutateAsync(taskId)
      onSelect(conv.id)
    } catch (e) {
      toast(errMsg(e), 'error')
    }
  }

  const handleRename = async (id: string) => {
    const title = renameValue.trim()
    try {
      if (title) await renameConv.mutateAsync({ id, title })
    } catch (e) {
      toast(errMsg(e), 'error')
    }
    setRenamingId(null)
    setMenuFor(null)
  }

  const handleTaskRename = async (task: Task) => {
    const title = taskRenameValue.trim()
    try {
      if (title && title !== task.title) await renameTask.mutateAsync({ id: task.id, title })
    } catch (e) {
      toast(errMsg(e), 'error')
    }
    setRenamingTask(null)
    setTaskMenuFor(null)
  }

  const handleDelete = async () => {
    if (!confirmDelete) return
    const deletingId = confirmDelete.id
    // 删除前先算出邻近会话：若删的是当前选中项，就近选择相邻会话避免空窗欢迎态闪现
    const neighbors = conversations.filter((c) => c.id !== deletingId)
    const willReset = deletingId === selectedId
    try {
      await deleteConv.mutateAsync(deletingId)
    } catch (e) {
      // 弹窗保持打开：内联红字展示失败原因，按钮恢复可点可重试
      setConfirmError(errMsg(e))
      return
    }
    setConfirmDelete(null)
    setConfirmError(null)
    if (willReset) {
      if (neighbors.length > 0) onSelect(neighbors[0].id)
      else onSelect(null)
    }
  }

  const handleDeleteTask = async () => {
    if (!confirmDeleteTask) return
    const tid = confirmDeleteTask.id
    const survivors = conversations.filter((c) => c.task_id !== tid)
    const willReset = conversations.some((c) => c.id === selectedId && c.task_id === tid)
    try {
      await deleteTaskM.mutateAsync(tid)
    } catch (e) {
      // 弹窗保持打开：内联红字展示失败原因，按钮恢复可点可重试
      setConfirmError(errMsg(e))
      return
    }
    setConfirmDeleteTask(null)
    setConfirmError(null)
    // 同步清掉上传归属任务：会话切换/列表刷新到位前重挂载的输入区不再拿着
    // 已删任务的 taskScope 去拉 files（否则吃到一次 404）
    setTaskScope(null)
    if (willReset) {
      if (survivors.length > 0) onSelect(survivors[0].id)
      else onSelect(null)
    }
  }

  return (
    <aside
      className={cn('side', collapsed && 'collapsed', dragging && 'dragging')}
      style={collapsed ? undefined : { width }}
    >
      <div
        className="resizer"
        onMouseDown={(e) => {
          if (collapsed) return
          e.preventDefault()
          appRect.current = e.currentTarget.closest('.app')?.getBoundingClientRect() ?? null
          setDragging(true)
          const onMove = (ev: MouseEvent) => {
            if (!appRect.current) return
            setWidth(Math.max(SIDE_MIN_W, Math.min(SIDE_MAX_W, ev.clientX - appRect.current.left)))
          }
          const onUp = () => {
            setDragging(false)
            window.removeEventListener('mousemove', onMove)
            window.removeEventListener('mouseup', onUp)
          }
          window.addEventListener('mousemove', onMove)
          window.addEventListener('mouseup', onUp)
        }}
      />
      {/* 收缩钮常驻侧栏头部最左（mac 上红绿灯右侧）；收起后展开钮由 ChatHeader 接管 */}
      <div className="side-head" data-tauri-drag-region>
        <button
          type="button"
          className="head-toggle"
          title="收起侧栏"
          onClick={() => {
            setWidth(SIDE_DEFAULT_W)
            onCollapse()
          }}
        >
          <PanelLeftClose />
        </button>
      </div>
      <div className="side-scroll">
        <div className="quick-list">
          <NavRow icon={<Plus />} label="新建任务" onClick={onNewSession} />
          {/* 占位入口：页面未落地前不给任何真实副作用（曾误绑设置弹窗/展开产物面板） */}
          <NavRow
            icon={<Package />}
            label="投标工作台"
            onClick={() => toast('投标工作台即将上线', 'info')}
          />
          <NavRow
            icon={<BookOpen />}
            label="知识库"
            active={activeView === 'kb'}
            badge={(kbBadge.data?.pending ?? 0) > 0}
            onClick={onOpenKnowledge}
          />
        </div>

        {/* count=任务（文件夹）数：子项是任务文件夹树，不是会话数 */}
        <NavSection title="任务" count={groupByTask(tasks, conversations).length}>
          {isLoading && <p className="px-3 py-1 text-xs text-muted-foreground">加载中…</p>}
          {!isLoading && tasks.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">还没有任务，点「新建任务」开始</p>
          )}
          {groupByTask(tasks, conversations).map((g) => (
            <TaskFolder
              key={g.task.id}
              task={g.task}
              builtIn={g.task.id === '__none__'}
              renaming={renamingTask?.id === g.task.id}
              renameValue={taskRenameValue}
              menuOpen={taskMenuFor === g.task.id}
              onRenameValue={setTaskRenameValue}
              onStartRename={() => {
                setRenamingTask(g.task)
                setTaskRenameValue(g.task.title)
                setTaskMenuFor(null)
              }}
              onConfirmRename={() => void handleTaskRename(g.task)}
              onCancelRename={() => setRenamingTask(null)}
              onMenuToggle={() => setTaskMenuFor(taskMenuFor === g.task.id ? null : g.task.id)}
              onDelete={() => {
                setTaskMenuFor(null)
                setConfirmError(null)
                setConfirmDeleteTask(g.task)
              }}
              onNewConversation={() => void handleNewConv(g.task.id)}
            >
              {g.conversations.map((c) => (
                <ConvItem
                  key={c.id}
                  conv={c}
                  active={c.id === selectedId}
                  renaming={renamingId === c.id}
                  renameValue={renameValue}
                  menuOpen={menuFor === c.id}
                  onRenameValue={setRenameValue}
                  onSelect={() => onSelect(c.id)}
                  onMenuOpen={() => {
                    setMenuFor(menuFor === c.id ? null : c.id)
                    setRenamingId(null)
                  }}
                  onStartRename={() => {
                    setRenamingId(c.id)
                    setRenameValue(c.title)
                    setMenuFor(null)
                  }}
                  onConfirmRename={() => void handleRename(c.id)}
                  onCancelRename={() => setRenamingId(null)}
                  onDelete={() => {
                    setMenuFor(null)
                    setConfirmError(null)
                    setConfirmDelete(c)
                  }}
                />
              ))}
            </TaskFolder>
          ))}
        </NavSection>
      </div>

      <UserBar
        name="本地工作区"
        actions={
          <>
            <span
              className={cn('h-2 w-2 rounded-full', STATUS_DOT[sidecarStatus])}
              title={`服务${STATUS_LABEL[sidecarStatus]}`}
            />
            <IconButtonAction title="设置" onClick={onOpenSettings}>
              <Settings className="h-4 w-4" />
            </IconButtonAction>
          </>
        }
      />

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => {
              setConfirmDelete(null)
              setConfirmError(null)
            }}
            aria-hidden
          />
          <div className="relative z-10 w-full max-w-sm rounded-xl border bg-card p-6 shadow-md">
            <h2 className="text-base font-semibold">删除会话</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              删除「{confirmDelete.title}」？其消息与本会话产物将一并删除，项目文件保留。
            </p>
            {confirmError && <p className="mt-2 text-sm text-error">删除失败：{confirmError}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setConfirmDelete(null)
                  setConfirmError(null)
                }}
              >
                取消
              </Button>
              <Button variant="destructive" size="sm" onClick={() => void handleDelete()} disabled={deleteConv.isPending}>
                删除
              </Button>
            </div>
          </div>
        </div>
      )}

      {confirmDeleteTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => {
              setConfirmDeleteTask(null)
              setConfirmError(null)
            }}
            aria-hidden
          />
          <div className="relative z-10 w-full max-w-sm rounded-xl border bg-card p-6 shadow-md">
            <h2 className="text-base font-semibold">删除任务</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              删除任务「{confirmDeleteTask.title}」？其下全部会话、消息与会话产物将被删除，
              项目文件移入归档目录（可手工找回）。此操作不可撤销。
            </p>
            {confirmError && <p className="mt-2 text-sm text-error">删除失败：{confirmError}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setConfirmDeleteTask(null)
                  setConfirmError(null)
                }}
              >
                取消
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => void handleDeleteTask()}
                disabled={deleteTaskM.isPending}
              >
                删除任务
              </Button>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}

/** 任务文件夹：头部（折叠/名称/内联重命名/hover 新会话 + ··· 菜单）+ 会话列表。 */
function TaskFolder({
  task,
  builtIn = false,
  renaming,
  renameValue,
  menuOpen,
  children,
  onRenameValue,
  onStartRename,
  onConfirmRename,
  onCancelRename,
  onMenuToggle,
  onDelete,
  onNewConversation,
}: {
  task: Task
  /** 内置分组（未归类兜底）：不可重命名/删除/新建会话 */
  builtIn?: boolean
  renaming: boolean
  renameValue: string
  menuOpen: boolean
  children: ReactNode
  onRenameValue: (v: string) => void
  onStartRename: () => void
  onConfirmRename: () => void
  onCancelRename: () => void
  onMenuToggle: () => void
  onDelete: () => void
  onNewConversation: () => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className={cn('nav-folder group/task', !open && 'collapsed')}>
      <div
        className="folder-head relative"
        onClick={() => {
          if (!renaming) setOpen(!open)
        }}
      >
        <span className="folder-ico">
          <Folder className="folder ico-closed" />
          <FolderOpen className="folder ico-open" />
        </span>
        {renaming ? (
          <input
            autoFocus
            value={renameValue}
            onChange={(e) => onRenameValue(e.target.value)}
            onBlur={onConfirmRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onConfirmRename()
              if (e.key === 'Escape') onCancelRename()
            }}
            className="my-0.5 w-full rounded-md border border-primary bg-transparent px-2 py-1 text-sm focus:outline-none"
          />
        ) : (
          <span className="flex-1 truncate" title={task.title}>
            {task.title}
          </span>
        )}
        {!builtIn && (
          <>
            <button
              type="button"
              data-menu
              title="在此任务新建会话"
              onClick={(e) => {
                e.stopPropagation()
                onNewConversation()
              }}
              className="rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground group-hover/task:opacity-100"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              type="button"
              data-menu
              title="更多操作"
              onClick={(e) => {
                e.stopPropagation()
                onMenuToggle()
              }}
              className="rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground group-hover/task:opacity-100"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
            {menuOpen && (
              <div
                className="absolute right-1 top-full z-20 mt-0.5 w-28 rounded-lg border bg-card py-1 shadow-md"
                data-menu
              >
                <button
                  type="button"
                  onClick={onStartRename}
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-sm hover:bg-muted"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  重命名
                </button>
                <button
                  type="button"
                  onClick={onDelete}
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-sm text-error hover:bg-muted"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  删除任务
                </button>
              </div>
            )}
          </>
        )}
      </div>
      <div className="nav-sub">{children}</div>
    </div>
  )
}

function IconButtonAction({
  title,
  onClick,
  children,
}: {
  title: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      {children}
    </button>
  )
}

function ConvItem({
  conv,
  active,
  renaming,
  renameValue,
  menuOpen,
  onRenameValue,
  onSelect,
  onMenuOpen,
  onStartRename,
  onConfirmRename,
  onCancelRename,
  onDelete,
}: {
  conv: Conversation
  active: boolean
  renaming: boolean
  renameValue: string
  menuOpen: boolean
  onRenameValue: (v: string) => void
  onSelect: () => void
  onMenuOpen: () => void
  onStartRename: () => void
  onConfirmRename: () => void
  onCancelRename: () => void
  onDelete: () => void
}) {
  if (renaming) {
    return (
      <input
        autoFocus
        value={renameValue}
        onChange={(e) => onRenameValue(e.target.value)}
        onBlur={onCancelRename}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onConfirmRename()
          if (e.key === 'Escape') onCancelRename()
        }}
        className="my-0.5 w-full rounded-md border border-primary bg-transparent px-2 py-1 text-sm focus:outline-none"
      />
    )
  }
  return (
    <div className="relative">
      <ChatItem
        title={conv.title}
        meta={formatRelativeTime(conv.created_at)}
        active={active}
        onClick={onSelect}
        action={
          <button
            type="button"
            data-menu
            title="更多操作"
            onClick={(e) => {
              e.stopPropagation()
              onMenuOpen()
            }}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
        }
      />
      {menuOpen && (
        <div
          className="absolute right-1 top-full z-20 mt-0.5 w-28 rounded-lg border bg-card py-1 shadow-md"
          data-menu
        >
          <button
            type="button"
            onClick={onStartRename}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-sm hover:bg-muted"
          >
            <Pencil className="h-3.5 w-3.5" />
            重命名
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-sm text-error hover:bg-muted"
          >
            <Trash2 className="h-3.5 w-3.5" />
            删除
          </button>
        </div>
      )}
    </div>
  )
}

/** 会话按任务分组：任务顺序 = tasks 列表序（新任务在前）；无归属的旧会话兜底进「未归类」。 */
function groupByTask(
  tasks: Task[],
  conversations: Conversation[],
): Array<{ task: Task; conversations: Conversation[] }> {
  const groups = tasks.map((task) => ({
    task,
    conversations: conversations.filter((c) => c.task_id === task.id),
  }))
  const orphans = conversations.filter((c) => !c.task_id || !tasks.some((t) => t.id === c.task_id))
  if (orphans.length > 0) {
    groups.push({
      task: {
        id: '__none__',
        title: '未归类',
        progress_note: '',
        created_at: orphans[0].created_at,
      },
      conversations: orphans,
    })
  }
  return groups
}
