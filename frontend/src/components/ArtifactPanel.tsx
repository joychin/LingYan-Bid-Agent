import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FileText, Maximize2, Minimize2 } from 'lucide-react'
import type { Artifact, FileItem, Task, WorkbenchFile } from '@/api/client'
import {
  getWorkbenchContent,
  isTauri,
  revealInFolder,
  restoreArtifact,
} from '@/api/client'
import { useTaskArtifacts, useConversationArtifacts } from '@/hooks/useArtifacts'
import { useFiles } from '@/hooks/useFiles'
import { useWorkbench } from '@/hooks/useWorkbench'
import { ArtifactOpenHost } from '@/components/ArtifactOpenHost'
import { DocxView } from '@/components/DocxView'
import { SourceView, sourcePreviewable } from '@/components/SourceView'
import { WorkbenchViewer } from '@/components/WorkbenchViewer'
import { GuideFileView } from '@/components/workbench/GuideFileView'
import { PromiseFileView } from '@/components/workbench/PromiseFileView'
import { Loader } from '@/components/ai/Loader'
import { ContextMenu } from '@/components/ui/ContextMenu'
import type { ContextMenuItem } from '@/components/ui/ContextMenu'
import { useToast } from '@/context/Toast'
import { fileExtIcon, kindIcon } from '@/artifacts/registry'
import { cn, downloadText, formatSize } from '@/lib/utils'

const DEFAULT_W = 300
const MIN_W = 240
const MAX_W = 560
/* 工作区覆盖态（.ap-shell.wide）宽度：与窄态列宽分开记忆；可拖面板左缘调节，
 * 上限动态计算给聊天区留 ≥360px */
const WS_DEFAULT_W = 1000
const WS_MIN_W = 640
const wsMaxW = () => Math.max(WS_MIN_W, window.innerWidth - 360)
/* 窄态列宽上限同样视口感知：聊天区至少留 360px（侧栏按 264 估），小窗口拖不 crush 聊天 */
const navMaxW = () => Math.max(MIN_W, Math.min(MAX_W, window.innerWidth - 264 - 360))

/**
 * 产物面板 v5（2026-09-04 两态移除）：任务归属 + 单一当前版本 + 业务流任务树。
 *
 * 树 = 业务流分类夹（平台封闭）：输入文件（sources 只读）/ 解析 / 分析 / 目录 / 正文 / 笔记。
 * 产物按其 kind 归入对应夹（投标目录→目录夹、笔记→笔记夹），过程文件（work/ 下 parse|analysis|
 * outline|body）与产物同夹并排，靠图标 + 徽章区分。
 * 会话批注 = 纯高亮：产物按 provenance（当前会话产出）行名着品牌 tint（.from-conv）。
 * 覆盖式工作区（宽态编辑器）沿用 v3。
 */

/** 工作台文件显示名：分析八件+目录主文件用业务名，其余用文件名。 */
const WB_NAMES: Record<string, string> = {
  'analysis/structure.md': '结构事实',
  'analysis/requirements-qualification.md': '资格要求',
  'analysis/requirements-submission.md': '递交要求',
  'analysis/requirements-business.md': '商务技术要求',
  'analysis/requirements-format.md': '格式要求',
  'analysis/disqualification.md': '废标条款',
  'analysis/evaluation.md': '评分标准',
  'analysis/clarifications.md': '待澄清',
  'outline/tender-response-docs.md': '投标目录（工作表）',
  'body/写作指引.md': '写作指引',
  'body/关键事实与承诺.md': '关键事实与承诺',
}

/** 业务流分类夹（平台封闭）。产物按其 kind 归入 group；过程文件按 path 前缀归入 group。 */
const GROUPS: { key: string; label: string }[] = [
  { key: 'sources', label: '输入文件' },
  { key: 'parse', label: '解析' },
  { key: 'analysis', label: '分析' },
  { key: 'outline', label: '目录' },
  { key: 'body', label: '正文' },
  { key: 'note', label: '笔记' },
]

/** 右键菜单目标行（来源原件 / 工作台文件 / 产物；菜单项按 kind 差异化）。 */
type RowMenuTarget =
  | { kind: 'source'; file: FileItem }
  | { kind: 'workbench'; file: WorkbenchFile }
  | { kind: 'artifact'; artifact: Artifact }

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function ArtifactPanel({
  currentConvId,
  currentTask,
  collapsed,
  previewId,
  workbenchPath,
  workbenchAnchor,
  sourceFile,
  onOpen,
  onOpenWorkbench,
  onOpenSource,
  onClearPreview,
}: {
  currentConvId: string | null
  currentTask: Task | null
  collapsed: boolean
  previewId: string | null
  workbenchPath: string | null
  /** 打开工作台文件时的行号定位（来源追溯「查看原文上下文」）；null=不定位 */
  workbenchAnchor: number | null
  /** 来源原件预览（sources/ 的 pdf/docx/图片，输入文件只读） */
  sourceFile: string | null
  onOpen: (id: string) => void
  onOpenWorkbench: (path: string, anchorLine?: number) => void
  onOpenSource: (name: string) => void
  onClearPreview: () => void
}) {
  const { data: taskArtifacts = [], isLoading: loadingTask } = useTaskArtifacts(currentTask?.id ?? null)
  const { data: convArtifacts = [] } = useConversationArtifacts(currentConvId)
  const { data: workbench = [], isLoading: loadingWorkbench } = useWorkbench(currentTask?.id ?? null)
  const { data: sourceFiles = [], isLoading: loadingFiles } = useFiles(currentTask?.id ?? null)
  const [width, setWidth] = useState(DEFAULT_W)
  const [wsWidth, setWsWidth] = useState(() => Math.min(WS_DEFAULT_W, wsMaxW()))
  const [dragging, setDragging] = useState(false)
  const appRect = useRef<DOMRect | null>(null)
  // 行级右键菜单（fixed 浮层，与编辑器 Esc/点选互不干扰见 ContextMenu）
  const [menu, setMenu] = useState<{ x: number; y: number; target: RowMenuTarget } | null>(null)
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const wsOpen = !collapsed && (!!previewId || !!workbenchPath || !!sourceFile)

  const copyText = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast(`${what}已复制`)
    } catch (e) {
      toast(errMsg(e), 'error')
    }
  }

  const reveal = (absPath: string) => {
    revealInFolder(absPath).catch((e) => toast(errMsg(e), 'error'))
  }

  /** md 另存为：拉全文副本下载（不动任务文件本体）。 */
  const saveMdCopy = async (f: WorkbenchFile) => {
    try {
      if (!currentTask) return
      const { content } = await getWorkbenchContent(currentTask.id, f.path)
      downloadText(f.path.split('/').pop() ?? '未命名.md', content)
    } catch (e) {
      toast(errMsg(e), 'error')
    }
  }

  /** 产物恢复上一版（恢复本身也留底可再撤销；与处理器内按钮同一范式）。 */
  const restorePrev = async (id: string) => {
    try {
      await restoreArtifact(id)
      toast('已恢复上一版', 'success')
      await queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    } catch (e) {
      toast(errMsg(e), 'error')
    }
  }

  const menuItems = (t: RowMenuTarget): ContextMenuItem[] => {
    if (t.kind === 'source') {
      return [
        ...(isTauri() ? [{ label: '打开文件夹', action: () => reveal(t.file.abs_path) }] : []),
        {
          label: '复制路径',
          action: () => void copyText(`${currentTask?.id ?? ''}/sources/${t.file.name}`, '路径'),
        },
      ]
    }
    if (t.kind === 'workbench') {
      const f = t.file
      return [
        { label: '打开', action: () => onOpenWorkbench(f.path) },
        ...(isTauri() ? [{ label: '打开文件夹', action: () => reveal(f.abs_path) }] : []),
        // 带 <task_id>/ 前缀 = 任务上下文里模型的引用口径，粘贴即可被直接寻址
        {
          label: '复制路径',
          action: () => void copyText(`${currentTask?.id ?? ''}/work/${f.path}`, '路径'),
        },
        ...(f.path.endsWith('.md')
          ? [{ label: '另存为…', action: () => void saveMdCopy(f) }]
          : []),
      ]
    }
    const a = t.artifact
    return [
      { label: '打开', action: () => onOpen(a.artifact_id) },
      ...(isTauri() ? [{ label: '打开文件夹', action: () => reveal(a.path) }] : []),
      ...(a.restore_available ? [{ label: '恢复上一版', action: () => void restorePrev(a.artifact_id) }] : []),
    ]
  }

  // 本会话产出的产物 id 集合（provenance → 高亮）
  const convArtifactIds = new Set(convArtifacts.map((a) => a.artifact_id))

  // 工作区态 Esc = 收起编辑器回导航（模态壳消失后由面板接管）
  useEffect(() => {
    if (!wsOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClearPreview()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [wsOpen, onClearPreview])

  // 解析去重：每个源文件只列一行主稿（<stem>.md）
  const parseFiles = workbench.filter((f) => f.path.startsWith('parse/'))
  const seenParse = new Set<string>()
  const parseRows: WorkbenchFile[] = []
  for (const f of parseFiles) {
    const src = f.path.split('/')[1] ?? ''
    if (!src || seenParse.has(src)) continue
    seenParse.add(src)
    const main = parseFiles.find((p) => p.path === `parse/${src}/${src}.md`) ?? f
    parseRows.push(main)
  }
  const analysisFiles = workbench.filter((f) => f.path.startsWith('analysis/'))
  const outlineFiles = workbench.filter((f) => f.path.startsWith('outline/') && !f.path.startsWith('outline/fragments/'))
  const fragmentFiles = workbench.filter((f) => f.path.startsWith('outline/fragments/'))
  const bodyFiles = workbench.filter((f) => f.path.startsWith('body/'))

  // 目录夹：目录产物 + 工作表 + fragments
  const directoryArtifacts = taskArtifacts.filter((a) => a.kind === 'tender.directory')
  const noteArtifacts = taskArtifacts.filter((a) => a.kind === 'doc.note')

  const openMenu = (e: React.MouseEvent, target: RowMenuTarget) => {
    e.preventDefault()
    setMenu({ x: e.clientX, y: e.clientY, target })
  }

  /** 输入文件行：可预览类型（pdf/docx/图片）点击进面板预览；其余只读展示。 */
  const sourceRow = (f: FileItem) => {
    const previewable = sourcePreviewable(f.name)
    const icon = fileExtIcon(f.name)
    return (
      <div
        key={f.name}
        className={cn('ap-row compact', !previewable && 'readonly')}
        title={previewable ? `${f.name}（点击预览）` : `${f.name}（输入文件，只读）`}
        onClick={previewable ? () => onOpenSource(f.name) : undefined}
        onContextMenu={(e) => openMenu(e, { kind: 'source', file: f })}
      >
        <span className={cn('ft-ico', icon.cls)}>{icon.mark}</span>
        <span className="ap-row-name truncate">{f.name}</span>
        <span className="ap-row-tail">
          <span className="ap-status regen">{formatSize(f.size)}</span>
        </span>
      </div>
    )
  }

  const artifactRow = (a: Artifact) => {
    const fromConv = convArtifactIds.has(a.artifact_id)
    const icon = kindIcon(a.kind)
    return (
      <div
        key={a.artifact_id}
        className={cn('ap-row', fromConv && 'from-conv')}
        onClick={() => onOpen(a.artifact_id)}
        onContextMenu={(e) => openMenu(e, { kind: 'artifact', artifact: a })}
      >
        {icon ? (
          <span className={cn('ft-ico', icon.cls)}>{icon.mark}</span>
        ) : (
          <span className="ft-ico-glyph">
            <FileText className="ft-ico-svg" />
          </span>
        )}
        <span className="ap-row-name truncate">{a.display_name}</span>
      </div>
    )
  }

  const wbRow = (f: WorkbenchFile, name?: string) => {
    // 图标按扩展名（.docx=W 徽章，与素材库/知识库同一色板族）
    const icon = fileExtIcon(f.path)
    return (
      <div
        key={f.path}
        className="ap-row compact"
        onClick={() => onOpenWorkbench(f.path)}
        title={f.path}
        onContextMenu={(e) => openMenu(e, { kind: 'workbench', file: f })}
      >
        <span className={cn('ft-ico', icon.cls)}>{icon.mark}</span>
        <span className="ap-row-name truncate">{name ?? WB_NAMES[f.path] ?? f.path.split('/').pop()}</span>
        <span className="ap-row-tail">
          <span className="ap-status regen">
            {f.editable ? '可重生成' : f.path.endsWith('.docx') ? 'Word 正文' : '解析只读'}
          </span>
        </span>
      </div>
    )
  }

  const loading = loadingTask || loadingWorkbench || loadingFiles

  return (
    <div
      className={cn('ap-slot', collapsed && 'collapsed', dragging && 'dragging')}
      style={collapsed ? undefined : { width: wsOpen ? undefined : width }}
    >
        <aside
          className={cn('ap-shell', wsOpen && 'wide', collapsed && 'collapsed', dragging && 'dragging')}
          style={collapsed ? undefined : { width: wsOpen ? wsWidth : width }}
        >
          <div className="ap-nav">
          <div
            className="resizer"
            onMouseDown={(e) => {
              if (collapsed) return
              e.preventDefault()
              appRect.current = e.currentTarget.closest('.app')?.getBoundingClientRect() ?? null
              setDragging(true)
              const onMove = (ev: MouseEvent) => {
                if (!appRect.current) return
                const next = appRect.current.right - ev.clientX
                if (wsOpen) setWsWidth(Math.max(WS_MIN_W, Math.min(wsMaxW(), next)))
                else setWidth(Math.max(MIN_W, Math.min(navMaxW(), next)))
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
          <div className="ap-head">
            <span className="ap-head-title">任务文件 · {currentTask?.title ?? '当前任务'}</span>
            <div className="ap-head-actions">
              {wsOpen ? (
                <button type="button" className="panel-btn" title="缩小面板" onClick={onClearPreview}>
                  <Minimize2 />
                </button>
              ) : (
                <button
                  type="button"
                  className="panel-btn"
                  title="放大面板（打开最近产物）"
                  disabled={taskArtifacts.length === 0}
                  onClick={() => {
                    const target = taskArtifacts[0]
                    if (target) onOpen(target.artifact_id)
                  }}
                >
                  <Maximize2 />
                </button>
              )}
            </div>
          </div>

          <div className="ap-body">
            {loading ? (
              <div className="ap-empty flex items-center gap-1.5">
                <Loader variant="classic" size="sm" tone="muted" />
                加载中…
              </div>
            ) : taskArtifacts.length === 0 && workbench.length === 0 && sourceFiles.length === 0 ? (
              <p className="ap-empty">
                任务还没有文件。
                <br />
                Agent 解析、分析、生成目录或笔记后，会显示在这里。
              </p>
            ) : (
              GROUPS.map((g) => {
                const rows: ReactNode[] = []
                // 产物
                if (g.key === 'outline') {
                  directoryArtifacts.forEach((a) => rows.push(artifactRow(a)))
                } else if (g.key === 'note') {
                  noteArtifacts.forEach((a) => rows.push(artifactRow(a)))
                }
                // 输入文件（只读行）与过程文件
                if (g.key === 'sources') sourceFiles.forEach((f) => rows.push(sourceRow(f)))
                else if (g.key === 'parse') parseRows.forEach((f) => rows.push(wbRow(f, f.path.split('/')[1])))
                else if (g.key === 'analysis') analysisFiles.forEach((f) => rows.push(wbRow(f)))
                else if (g.key === 'outline') {
                  outlineFiles.forEach((f) => rows.push(wbRow(f)))
                  fragmentFiles.forEach((f) => {
                    const stem = (f.path.split('/').pop() ?? '').replace(/\.[^.]+$/, '')
                    rows.push(wbRow(f, `分册 · ${stem}`))
                  })
                } else if (g.key === 'body') bodyFiles.forEach((f) => rows.push(wbRow(f)))

                if (rows.length === 0) return null
                return (
                  <div className="ap-group" key={g.key}>
                    <div className="ap-group-head">
                      <span>{g.label}</span>
                      {rows.length > 0 && <span className="ap-count">{rows.length}</span>}
                    </div>
                    {rows}
                  </div>
                )
              })
            )}
          </div>
          </div>
          {wsOpen &&
            (sourceFile ? (
              // 来源原件预览（sources/ 只读）：absPath 从列表行取（列表是点击入口，
              // 数据必然在缓存）；key=文件名，切文件即卸载重挂（与下同款纪律）
              <SourceView
                key={sourceFile}
                taskId={currentTask?.id ?? null}
                name={sourceFile}
                absPath={sourceFiles.find((f) => f.name === sourceFile)?.abs_path}
              />
            ) : workbenchPath ? (
              // key=路径：切文件即卸载重挂——WorkbenchViewer 的卸载冲刷 effect 捕获
              // 挂载期 path/taskId（[] 依赖），同实例换 path 会把新文件内容 PUT 到
              // 旧路径（跨文件串写）；重挂后闭包恒持有本实例自己的正确路径。
              // anchorLine 不进 key：同文件不同行的追溯定位靠 WorkbenchViewer 内
              // effect 响应 anchorLine 变化。docx（tender-body 正文/整本）走只读
              // 视图（DocxView），无编辑态故无串写面，key 同款只为查询独立。
              // 写作指引/承诺清单走结构化表格视图（basename 分发——模型给的
              // guide_path 可能带前缀变体，服务端 _resolve 兜底寻址，这里按文件名认）。
              workbenchPath.endsWith('.docx') ? (
                <DocxView key={workbenchPath} taskId={currentTask?.id ?? null} path={workbenchPath} />
              ) : workbenchPath.split('/').pop() === '写作指引.md' ? (
                <GuideFileView
                  key={workbenchPath}
                  taskId={currentTask?.id ?? null}
                  path={workbenchPath}
                  onOpenWorkbench={onOpenWorkbench}
                />
              ) : workbenchPath.split('/').pop() === '关键事实与承诺.md' ? (
                <PromiseFileView key={workbenchPath} taskId={currentTask?.id ?? null} path={workbenchPath} />
              ) : (
                <WorkbenchViewer
                  key={workbenchPath}
                  taskId={currentTask?.id ?? null}
                  path={workbenchPath}
                  anchorLine={workbenchAnchor}
                />
              )
            ) : (
              <ArtifactOpenHost artifactId={previewId} onOpenWorkbench={onOpenWorkbench} />
            ))}
        </aside>
        {menu && !collapsed && (
          <ContextMenu
            x={menu.x}
            y={menu.y}
            items={menuItems(menu.target)}
            onClose={() => setMenu(null)}
          />
        )}
      </div>
  )
}
