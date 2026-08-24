import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDown, Folder, MoreHorizontal, Package, PanelLeftClose, Pencil, Plus, Settings, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useRenameConversation,
} from '@/hooks/useConversations'
import { useSidecarHealth } from '@/context/SidecarHealth'
import { useToast } from '@/context/Toast'
import { cn, dayBucket, formatRelativeTime } from '@/lib/utils'
import type { Conversation } from '@/api/client'
import { ChatItem } from '@/components/workspace/ChatItem'
import { NavRow } from '@/components/workspace/NavRow'
import { NavSection } from '@/components/workspace/NavSection'
import { UserBar } from '@/components/workspace/UserBar'

export interface SidebarProps {
  selectedId: string | null
  onSelect: (id: string | null) => void
  onOpenSettings: () => void
  onOpenArtifacts: () => void
  collapsed: boolean
  onCollapse: () => void
}

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

/** Workspace 侧栏：快捷导航 + 「会话」分区（按天分组文件夹）+ 用户栏。 */
export function Sidebar({
  selectedId,
  onSelect,
  onOpenSettings,
  onOpenArtifacts,
  collapsed,
  onCollapse,
}: SidebarProps) {
  const { data: conversations = [], isLoading } = useConversations()
  const createConv = useCreateConversation()
  const renameConv = useRenameConversation()
  const deleteConv = useDeleteConversation()
  const { status: sidecarStatus } = useSidecarHealth()
  const { toast } = useToast()
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<Conversation | null>(null)

  // 点击菜单外部区域时收起「···」菜单
  useEffect(() => {
    if (!menuFor) return
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node | null
      if (target && !(target as HTMLElement).closest?.('[data-conv-menu]')) setMenuFor(null)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [menuFor])

  const handleNew = async () => {
    if (createConv.isPending) return
    try {
      const conv = await createConv.mutateAsync()
      onSelect(conv.id)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  const handleRename = async (id: string) => {
    const title = renameValue.trim()
    try {
      if (title) await renameConv.mutateAsync({ id, title })
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
    setRenamingId(null)
    setMenuFor(null)
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
      setConfirmDelete(null)
      toast(e instanceof Error ? e.message : String(e), 'error')
      return
    }
    setConfirmDelete(null)
    if (willReset) {
      if (neighbors.length > 0) onSelect(neighbors[0].id)
      else onSelect(null)
    }
  }

  const groups = groupByDay(conversations)

  return (
    <aside className={cn('side', collapsed && 'collapsed')}>
      <div className="side-head">
        <span>工作区</span>
        <button type="button" title="收起侧栏" onClick={onCollapse}>
          <PanelLeftClose />
        </button>
      </div>
      <div className="side-scroll">
        <div className="quick-list">
          <NavRow icon={<Plus />} label="新建任务" onClick={handleNew} />
          <NavRow icon={<Package />} label="投标工作台" onClick={onOpenArtifacts} />
          <NavRow icon={<Settings />} label="知识库" onClick={onOpenSettings} />
        </div>

        <NavSection title="会话" count={conversations.length}>
          {isLoading && <p className="px-3 py-1 text-xs text-muted-foreground">加载中…</p>}
          {!isLoading && conversations.length === 0 && (
            <p className="px-3 py-2 text-xs text-muted-foreground">开始你的第一个对话</p>
          )}
          {groups.map(([label, items]) => (
            <DayFolder key={label} label={label}>
              {items.map((c) => (
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
                  onConfirmRename={() => handleRename(c.id)}
                  onCancelRename={() => setRenamingId(null)}
                  onDelete={() => setConfirmDelete(c)}
                />
              ))}
            </DayFolder>
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
          <div className="absolute inset-0 bg-black/40" onClick={() => setConfirmDelete(null)} aria-hidden />
          <div className="relative z-10 w-full max-w-sm rounded-xl border bg-card p-6 shadow-md">
            <h2 className="text-base font-semibold">删除会话</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              删除「{confirmDelete.title}」？其消息与运行记录将被移除，产物仍保留。
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(null)}>
                取消
              </Button>
              <Button variant="destructive" size="sm" onClick={handleDelete} disabled={deleteConv.isPending}>
                删除
              </Button>
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}

function DayFolder({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(true)
  return (
    <div className={cn('nav-folder', !open && 'collapsed')}>
      <div className="folder-head" onClick={() => setOpen(!open)}>
        <ChevronDown className="folder-chev" />
        <Folder className="folder" />
        <span className="truncate">{label}</span>
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
            data-conv-menu
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
          data-conv-menu
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

function groupByDay(list: Conversation[]): Array<[string, Conversation[]]> {
  const order: Record<string, number> = { 今天: 0, 昨天: 1, 更早: 2 }
  const groups = new Map<string, Conversation[]>()
  for (const c of list) {
    const k = dayBucket(c.created_at)
    if (!groups.has(k)) groups.set(k, [])
    groups.get(k)!.push(c)
  }
  return Array.from(groups.entries())
    .sort((a, b) => order[a[0]] - order[b[0]])
    .map(([k, v]) => [k, v])
}
