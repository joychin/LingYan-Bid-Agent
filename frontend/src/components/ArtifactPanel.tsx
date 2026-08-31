import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { FileText, Maximize2, Minimize2 } from 'lucide-react'
import type { Artifact, FileItem, Task, WorkbenchFile } from '@/api/client'
import { useTaskArtifacts, useConversationArtifacts, useUnconfirmArtifact } from '@/hooks/useArtifacts'
import { useFiles } from '@/hooks/useFiles'
import { useWorkbench } from '@/hooks/useWorkbench'
import { ConfirmModal } from '@/components/ConfirmModal'
import { ArtifactOpenHost } from '@/components/ArtifactOpenHost'
import { WorkbenchViewer } from '@/components/WorkbenchViewer'
import { Loader } from '@/components/ai/Loader'
import { kindIcon } from '@/artifacts/registry'
import { cn, formatSize } from '@/lib/utils'

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
 * 产物面板 v4（2026-08-31 重构）：任务归属 + 草稿/已确认两态 + 业务流任务树。
 *
 * 树 = 业务流分类夹（平台封闭）：输入文件（sources 只读）/ 解析 / 分析 / 目录 / 正文 / 笔记。
 * 产物按其 kind 归入对应夹（投标目录→目录夹、笔记→笔记夹），过程文件（work/ 下 parse|analysis|
 * outline|body）与产物同夹并排，靠图标 + 徽章区分。已确认留在业务夹内 + 夹内已确认置顶。
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

/** 输入文件行：sources/ 上传原件只读展示（无处理器可打开，仅列名与大小）。 */
const srcRow = (f: FileItem) => (
  <div key={f.name} className="ap-row compact readonly" title={`${f.name}（输入文件，只读）`}>
    <span className="ft-ico-glyph">
      <FileText className="ft-ico-svg" />
    </span>
    <span className="ap-row-name truncate">{f.name}</span>
    <span className="ap-row-tail">
      <span className="ap-status regen">{formatSize(f.size)}</span>
    </span>
  </div>
)

export function ArtifactPanel({
  currentConvId,
  currentTask,
  collapsed,
  previewId,
  workbenchPath,
  onOpen,
  onOpenWorkbench,
  onClearPreview,
}: {
  currentConvId: string | null
  currentTask: Task | null
  collapsed: boolean
  previewId: string | null
  workbenchPath: string | null
  onOpen: (id: string) => void
  onOpenWorkbench: (path: string) => void
  onClearPreview: () => void
}) {
  const { data: taskArtifacts = [], isLoading: loadingTask } = useTaskArtifacts(currentTask?.id ?? null)
  const { data: convArtifacts = [] } = useConversationArtifacts(currentConvId)
  const unconfirm = useUnconfirmArtifact()
  const { data: workbench = [], isLoading: loadingWorkbench } = useWorkbench(currentTask?.id ?? null)
  const { data: sourceFiles = [], isLoading: loadingFiles } = useFiles(currentTask?.id ?? null)
  const [width, setWidth] = useState(DEFAULT_W)
  const [wsWidth, setWsWidth] = useState(() => Math.min(WS_DEFAULT_W, wsMaxW()))
  const [confirmTarget, setConfirmTarget] = useState<Artifact | null>(null)
  const [dragging, setDragging] = useState(false)
  const appRect = useRef<DOMRect | null>(null)

  const wsOpen = !collapsed && (!!previewId || !!workbenchPath)

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

  // 目录夹：目录产物（已确认置顶）+ 工作表 + fragments
  const directoryArtifacts = taskArtifacts.filter((a) => a.kind === 'tender.directory')
  const noteArtifacts = taskArtifacts.filter((a) => a.kind === 'doc.note')

  const artifactRow = (a: Artifact) => {
    const confirmed = a.state === 'confirmed'
    const fromConv = convArtifactIds.has(a.artifact_id)
    const icon = kindIcon(a.kind)
    return (
      <div
        key={a.artifact_id}
        className={cn('ap-row', 'has-action', fromConv && 'from-conv')}
        onClick={() => onOpen(a.artifact_id)}
      >
        {icon ? (
          <span className={cn('ft-ico', icon.cls)}>{icon.mark}</span>
        ) : (
          <span className="ft-ico-glyph">
            <FileText className="ft-ico-svg" />
          </span>
        )}
        <span className="ap-row-name truncate">{a.display_name}</span>
        <span className="ap-row-tail">
          {confirmed ? (
            // 撤销确认直接执行（无确认弹窗）：与确认互逆、低风险——恢复为可被
            // AI 覆盖的草稿；toast + invalidate 由 useUnconfirmArtifact 统一处理
            <button
              type="button"
              className="ap-row-action"
              title="撤销确认：恢复为草稿（可被 AI 覆盖的工作稿）"
              onClick={(e) => {
                e.stopPropagation()
                unconfirm.mutate(a.artifact_id)
              }}
            >
              撤销
            </button>
          ) : (
            <button
              type="button"
              className="ap-row-action"
              title="确认为正式成果（不复制，可撤销）"
              onClick={(e) => {
                e.stopPropagation()
                setConfirmTarget(a)
              }}
            >
              确认
            </button>
          )}
          <span className={cn('ap-status', confirmed ? 'baseline' : 'regen')}>
            {confirmed ? '已确认' : '草稿'}
          </span>
        </span>
      </div>
    )
  }

  const wbRow = (f: WorkbenchFile, name?: string) => (
    <div key={f.path} className="ap-row compact" onClick={() => onOpenWorkbench(f.path)} title={f.path}>
      <span className="ft-ico-glyph">
        <FileText className="ft-ico-svg" />
      </span>
      <span className="ap-row-name truncate">{name ?? WB_NAMES[f.path] ?? f.path.split('/').pop()}</span>
      <span className="ap-row-tail">
        <span className="ap-status regen">{f.editable ? '可重生成' : '解析只读'}</span>
      </span>
    </div>
  )

  const loading = loadingTask || loadingWorkbench || loadingFiles

  return (
    <>
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
              <p className="ap-empty flex items-center gap-1.5">
                <Loader variant="classic" size="sm" tone="muted" />
                加载中…
              </p>
            ) : taskArtifacts.length === 0 && workbench.length === 0 && sourceFiles.length === 0 ? (
              <p className="ap-empty">
                任务还没有文件。
                <br />
                Agent 解析、分析、生成目录或笔记后，会显示在这里。
              </p>
            ) : (
              GROUPS.map((g) => {
                const rows: ReactNode[] = []
                // 产物（已确认置顶）
                if (g.key === 'outline') {
                  const sorted = directoryArtifacts.toSorted((a, b) =>
                    (a.state === 'confirmed' ? -1 : 0) - (b.state === 'confirmed' ? -1 : 0),
                  )
                  sorted.forEach((a) => rows.push(artifactRow(a)))
                } else if (g.key === 'note') {
                  const sorted = noteArtifacts.toSorted((a, b) =>
                    (a.state === 'confirmed' ? -1 : 0) - (b.state === 'confirmed' ? -1 : 0),
                  )
                  sorted.forEach((a) => rows.push(artifactRow(a)))
                }
                // 输入文件（只读行）与过程文件
                if (g.key === 'sources') sourceFiles.forEach((f) => rows.push(srcRow(f)))
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
            (workbenchPath ? (
              // key=路径：切文件即卸载重挂——WorkbenchViewer 的卸载冲刷 effect 捕获
              // 挂载期 path/taskId（[] 依赖），同实例换 path 会把新文件内容 PUT 到
              // 旧路径（跨文件串写）；重挂后闭包恒持有本实例自己的正确路径
              <WorkbenchViewer
                key={workbenchPath}
                taskId={currentTask?.id ?? null}
                conversationId={currentConvId}
                path={workbenchPath}
              />
            ) : (
              <ArtifactOpenHost artifactId={previewId} />
            ))}
        </aside>
      </div>
      <ConfirmModal artifact={confirmTarget} onClose={() => setConfirmTarget(null)} />
    </>
  )
}
