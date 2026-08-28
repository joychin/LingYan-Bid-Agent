import { useRef, useState } from 'react'
import { ChevronDown, ChevronRight, FileText, Folder, FolderOpen, Maximize2, Minimize2 } from 'lucide-react'
import type { Artifact, Task, WorkbenchFile } from '@/api/client'
import { useConversationArtifacts, useTaskArtifacts } from '@/hooks/useArtifacts'
import { useConversations } from '@/hooks/useConversations'
import { useWorkbench } from '@/hooks/useWorkbench'
import { kindIcon } from '@/artifacts/registry'
import { cn } from '@/lib/utils'

const DEFAULT_W = 300
const MIN_W = 240
const MAX_W = 560

/**
 * Workspace 右栏产物面板 v2：一棵朴素文件夹树——任务名为根，项目文件/会话产物
 * 是它的一级子文件夹，往下纯嵌套（工作台 = 任务 out/ 的 md 过程产物）。
 * 行上不带任何小字后缀（修订/来源状态在查看器头部徽章条里看）。
 * 无任务上下文（草稿态）时 App 不渲染本面板。
 */

/** 工作台文件的显示名：分析八件+目录主文件用业务名，其余（fragments/解析）用文件名。 */
const WB_NAMES: Record<string, string> = {
  'analysis/structure.md': '结构事实',
  'analysis/requirements-qualification.md': '资格要求',
  'analysis/requirements-submission.md': '递交要求',
  'analysis/requirements-business.md': '商务技术要求',
  'analysis/requirements-format.md': '格式要求',
  'analysis/disqualification.md': '废标条款',
  'analysis/evaluation.md': '评分标准',
  'analysis/clarifications.md': '待澄清',
  'outline/tender-response-docs.md': '投标目录（草稿）',
}

export function ArtifactPanel({
  currentConvId,
  currentTask,
  collapsed,
  onOpen,
  onOpenWorkbench,
  onCollapse,
}: {
  currentConvId: string | null
  currentTask: Task | null
  collapsed: boolean
  onOpen: (id: string) => void
  onOpenWorkbench: (path: string) => void
  onCollapse: () => void
}) {
  const { data: taskArtifacts = [], isLoading: loadingTask } = useTaskArtifacts(currentTask?.id ?? null)
  const { data: convArtifacts = [], isLoading: loadingConv } = useConversationArtifacts(currentConvId)
  const { data: conversations = [] } = useConversations()
  const { data: workbench = [], isLoading: loadingWorkbench } = useWorkbench(currentTask?.id ?? null)
  const convTitle = conversations.find((c) => c.id === currentConvId)?.title
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

  const artifactRow = (a: Artifact) => {
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
      </div>
    )
  }

  const wbRow = (f: WorkbenchFile) => (
    <div key={f.path} className="ft-row" onClick={() => onOpenWorkbench(f.path)} title={f.path}>
      <span className="ft-ico-glyph">
        <FileText className="ft-ico-svg" />
      </span>
      <span className="ft-name truncate">{WB_NAMES[f.path] ?? f.path.split('/').pop()}</span>
    </div>
  )

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
          <TreeFolder title={currentTask?.title ?? '任务'}>
            <TreeFolder
              title="项目文件"
              loading={loadingTask}
              empty={taskArtifacts.length === 0 ? '暂无 · 转正自会话产物' : undefined}
            >
              {taskArtifacts.map(artifactRow)}
            </TreeFolder>
            <TreeFolder
              title={convTitle ? `会话产物 · ${convTitle}` : '会话产物'}
              loading={loadingConv}
              empty={convArtifacts.length === 0 && workbench.length === 0 ? '暂无' : undefined}
            >
              {convArtifacts.map(artifactRow)}
              <WorkbenchTree files={workbench} loading={loadingWorkbench} row={wbRow} />
            </TreeFolder>
          </TreeFolder>
        </div>
      </aside>
      <button type="button" className="product-toggle" title="展开产物面板" onClick={handleCollapseToggle}>
        <ChevronRight />
      </button>
    </>
  )
}

/** 文件夹节点：头部 = 旋转箭头 + Folder/FolderOpen 交叉淡入，整行折叠；纯类名嵌套缩进。 */
function TreeFolder({
  title,
  titleHint,
  children,
  loading,
  empty,
}: {
  title: string
  titleHint?: string
  children?: React.ReactNode
  loading?: boolean
  empty?: string
}) {
  const [open, setOpen] = useState(true)
  return (
    <section className={cn('ft-folder', !open && 'collapsed')}>
      <button type="button" className="ft-folder-head" title={titleHint} onClick={() => setOpen(!open)}>
        <ChevronRight className="ft-chev" />
        <span className="ft-folder-ico">
          <Folder className="ico-closed" />
          <FolderOpen className="ico-open" />
        </span>
        <span className="ft-folder-title truncate">{title}</span>
      </button>
      <div className="ft-folder-body">
        {loading && <p className="ft-empty">加载产物…</p>}
        {!loading && empty !== undefined && <p className="ft-empty">{empty}</p>}
        {children}
      </div>
    </section>
  )
}

/** 工作文件子树：任务共享的 out/ 过程产物（解析/分析/目录），随当前会话展示。 */
function WorkbenchTree({
  files,
  loading,
  row,
}: {
  files: WorkbenchFile[]
  loading: boolean
  row: (f: WorkbenchFile) => React.ReactNode
}) {
  const parseFiles = files.filter((f) => f.path.startsWith('parse/'))
  const analysisFiles = files.filter((f) => f.path.startsWith('analysis/'))
  const outlineFiles = files.filter((f) => f.path.startsWith('outline/'))
  // 解析按源文件（第二段）分夹；目录下 fragments 归子夹
  const parseGroups = new Map<string, WorkbenchFile[]>()
  for (const f of parseFiles) {
    const src = f.path.split('/')[1] ?? ''
    parseGroups.set(src, [...(parseGroups.get(src) ?? []), f])
  }
  const outlineRoots = outlineFiles.filter((f) => !f.path.startsWith('outline/fragments/'))
  const fragments = outlineFiles.filter((f) => f.path.startsWith('outline/fragments/'))

  if (loading) {
    return (
      <TreeFolder title="工作文件" loading>
        <></>
      </TreeFolder>
    )
  }
  return (
    <TreeFolder
      title="工作文件"
      titleHint="任务内所有会话共享同一份工作文件（解析→分析→目录的过程产物）"
      empty={files.length === 0 ? '暂无 · 流水线产物' : undefined}
    >
      {parseGroups.size > 0 && (
        <TreeFolder title="解析">
          {[...parseGroups.entries()].map(([src, list]) => (
            <TreeFolder key={src} title={src}>
              {list.map(row)}
            </TreeFolder>
          ))}
        </TreeFolder>
      )}
      {analysisFiles.length > 0 && <TreeFolder title="分析">{analysisFiles.map(row)}</TreeFolder>}
      {outlineFiles.length > 0 && (
        <TreeFolder title="目录">
          {outlineRoots.map(row)}
          {fragments.length > 0 && <TreeFolder title="fragments">{fragments.map(row)}</TreeFolder>}
        </TreeFolder>
      )}
    </TreeFolder>
  )
}
