import { useRef, useState } from 'react'
import { ChevronDown, ChevronRight, FileText, Folder, FolderOpen, Maximize2, Minimize2 } from 'lucide-react'
import type { Artifact, Task } from '@/api/client'
import { useArtifacts, useConversationArtifacts, useTaskArtifacts } from '@/hooks/useArtifacts'
import { useConversations } from '@/hooks/useConversations'
import { useTasks } from '@/hooks/useTasks'
import { kindIcon } from '@/artifacts/registry'
import { cn } from '@/lib/utils'

const DEFAULT_W = 300
const MIN_W = 240
const MAX_W = 560

/**
 * Workspace 右栏产物面板：WorkBuddy 风格文件树，无徽标/无计数/无动作按钮。
 * 顶层两个根文件夹：正式稿（任务级）/ 过程稿（当前会话），各自独立展开。
 * 进度便签、转正入口、文件定位全部从面板剥离（ArtifactCard / ArtifactOpenHost 内已提供）。
 */
export function ArtifactPanel({
  currentConvId,
  currentTask,
  collapsed,
  onOpen,
  onCollapse,
}: {
  currentConvId: string | null
  currentTask: Task | null
  collapsed: boolean
  onOpen: (id: string) => void
  onCollapse: () => void
}) {
  const { data: allArtifacts = [], isLoading: loadingAll } = useArtifacts()
  const { data: taskArtifacts = [], isLoading: loadingTask } = useTaskArtifacts(currentTask?.id ?? null)
  const { data: convArtifacts = [], isLoading: loadingConv } = useConversationArtifacts(currentConvId)
  const { data: conversations = [] } = useConversations()
  const { data: tasks = [] } = useTasks()
  const convTitle = conversations.find((c) => c.id === currentConvId)?.title
  // 无任务上下文时退化为平铺（有会话则只看该会话，否则全量历史视图）
  const fallbackArtifacts = currentConvId ? convArtifacts : allArtifacts
  const fallbackLoading = currentConvId ? loadingConv : loadingAll
  const [width, setWidth] = useState(DEFAULT_W)
  const [expanded, setExpanded] = useState(false)
  const [closing, setClosing] = useState(false)
  const [dragging, setDragging] = useState(false)
  const appRect = useRef<DOMRect | null>(null)

  const handleCollapseToggle = () => {
    setExpanded(false)
    setClosing(false)
    setWidth(DEFAULT_W)
    onCollapse()
  }

  const handleExpandToggle = () => {
    if (expanded) {
      setClosing(true)
      window.setTimeout(() => {
        setExpanded(false)
        setClosing(false)
        setWidth(DEFAULT_W)
      }, 260)
    } else {
      setExpanded(true)
    }
  }

  const renderRow = (a: Artifact, subLabel?: string) => {
    const icon = kindIcon(a.kind)
    return (
      <div key={a.artifact_id} className="ft-row" onClick={() => onOpen(a.artifact_id)}>
        {icon ? (
          <span className={cn('ft-ico', icon.cls)}>{icon.mark}</span>
        ) : (
          <span className="ft-ico-glyph">
            <FileText className="ft-ico-svg" />
          </span>
        )}
        <span className="ft-name truncate">{a.display_name}</span>
        {subLabel && <span className="ft-row-sub">{subLabel}</span>}
      </div>
    )
  }
  return (
    <>
      <aside
        className={cn('product', collapsed && 'collapsed', expanded && 'expanded', closing && 'closing', dragging && 'dragging')}
        style={collapsed || expanded ? undefined : { width }}
      >
        <div
          className="resizer"
          onMouseDown={(e) => {
            if (collapsed || expanded) return
            e.preventDefault()
            appRect.current = e.currentTarget.closest('.app')?.getBoundingClientRect() ?? null
            setDragging(true)
            const onMove = (ev: MouseEvent) => {
              if (!appRect.current) return
              setWidth(Math.max(MIN_W, Math.min(MAX_W, appRect.current.right - ev.clientX)))
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
        <div
          className="product-head"
          onClick={handleCollapseToggle}
          title="收起面板"
          role="button"
        >
          <span className="product-title">工作空间文件</span>
          <ChevronDown className="product-chev" />
          <div className="panel-actions">
            <button
              type="button"
              className="panel-btn"
              title={expanded ? '缩小' : '放大'}
              onClick={(e) => {
                e.stopPropagation()
                handleExpandToggle()
              }}
            >
              {expanded ? <Minimize2 /> : <Maximize2 />}
            </button>
          </div>
        </div>

        <div className="product-body file-tree">
          {currentTask ? (
            <>
              <FolderSection
                title="正式稿"
                artifacts={taskArtifacts}
                isLoading={loadingTask}
                emptyText="暂无 · 转正自过程稿"
                renderRow={renderRow}
              />
              <FolderSection
                title={convTitle ? `过程稿 · ${convTitle}` : '过程稿'}
                artifacts={convArtifacts}
                isLoading={loadingConv}
                emptyText="暂无"
                renderRow={renderRow}
              />
            </>
          ) : (
            <>
              {fallbackLoading && <p className="ft-empty">加载产物…</p>}
              {!fallbackLoading && fallbackArtifacts.length === 0 && (
                <p className="ft-empty">{currentConvId ? '本会话还没有过程稿' : '还没有产物'}</p>
              )}
              {/* 无任务上下文的平铺视图按 artifact.task_id 标注归属任务，防跨任务同名产物混淆；
                  scope 后缀区分同任务的正式稿/过程稿两份（转正后同名成对出现） */}
              {fallbackArtifacts.map((a) =>
                renderRow(
                  a,
                  `${a.task_id ? (tasks.find((t) => t.id === a.task_id)?.title ?? '未归属') : '未归属'} · ${
                    a.scope === 'task' ? '正式稿' : '过程稿'
                  }`,
                ),
              )}
            </>
          )}
        </div>
      </aside>
      <button type="button" className="product-toggle" title="展开产物面板" onClick={handleCollapseToggle}>
        <ChevronRight />
      </button>
    </>
  )
}

/** 文件夹分区：头部 = 旋转箭头 + Folder/FolderOpen 交叉淡入，整行折叠；空态/加载各自独立。 */
function FolderSection({
  title,
  artifacts,
  isLoading,
  emptyText,
  renderRow,
}: {
  title: string
  artifacts: Artifact[]
  isLoading: boolean
  emptyText: string
  renderRow: (a: Artifact) => React.ReactNode
}) {
  const [open, setOpen] = useState(true)
  return (
    <section className={cn('ft-folder', !open && 'collapsed')}>
      <button type="button" className="ft-folder-head" onClick={() => setOpen(!open)}>
        <ChevronRight className="ft-chev" />
        <span className="ft-folder-ico">
          <Folder className="ico-closed" />
          <FolderOpen className="ico-open" />
        </span>
        <span className="ft-folder-title">{title}</span>
      </button>
      <div className="ft-folder-body">
        {isLoading && <p className="ft-empty">加载产物…</p>}
        {!isLoading && artifacts.length === 0 && <p className="ft-empty">{emptyText}</p>}
        {artifacts.map(renderRow)}
      </div>
    </section>
  )
}
