import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, FileText, Maximize2, Minimize2 } from 'lucide-react'
import type { Artifact, Task, WorkbenchFile } from '@/api/client'
import { useConversationArtifacts, useTaskArtifacts } from '@/hooks/useArtifacts'
import { useWorkbench } from '@/hooks/useWorkbench'
import { PromoteConfirmModal } from '@/components/PromoteConfirmModal'
import { ArtifactOpenHost } from '@/components/ArtifactOpenHost'
import { WorkbenchViewer } from '@/components/WorkbenchViewer'
import { kindIcon } from '@/artifacts/registry'
import { cn } from '@/lib/utils'

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
 * 产物面板 v3（方案 v2 阶段 4a/4b）：作用域分组列表 + 覆盖式工作区。
 *
 * 三分组 = 任务正式成果 / 本会话产物 / 任务工作台（默认折叠）；行 = 名称 + 一个状态标
 * （[任务基线]/[待转正]/[仅本会话]/[可重生成]/[解析只读]），提升动作（转正）hover 淡入、
 * 走 PromoteConfirmModal 确认。最深缩进 ≤2 层；转正信息对（同名正式稿↔草稿）分组相邻。
 * previewId / workbenchPath 非空时进入工作区态：面板向左覆盖展开（默认 1000px、
 * 拖左缘 640px～视口-360 可调，不挤压聊天），编辑器（ArtifactOpenHost / WorkbenchViewer）
 * 嵌入右侧；Esc 退回列表，右上角钉角开关收起整个面板（再展开回到原编辑位置）。
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
  'outline/tender-response-docs.md': '投标目录（草稿）',
}

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
  const { data: convArtifacts = [], isLoading: loadingConv } = useConversationArtifacts(currentConvId)
  const { data: workbench = [], isLoading: loadingWorkbench } = useWorkbench(currentTask?.id ?? null)
  const [width, setWidth] = useState(DEFAULT_W)
  const [wsWidth, setWsWidth] = useState(() => Math.min(WS_DEFAULT_W, wsMaxW()))
  const [wbOpen, setWbOpen] = useState(false)
  const [promoteTarget, setPromoteTarget] = useState<Artifact | null>(null)
  const [dragging, setDragging] = useState(false)
  const appRect = useRef<DOMRect | null>(null)

  const wsOpen = !collapsed && (!!previewId || !!workbenchPath)

  // 工作区态 Esc = 收起编辑器回导航（模态壳消失后由面板接管）
  useEffect(() => {
    if (!wsOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClearPreview()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [wsOpen, onClearPreview])

  const artifactRow = (a: Artifact) => {
    const formal = a.scope === 'task'
    const icon = kindIcon(a.kind)
    return (
      <div
        key={a.artifact_id}
        className={cn('ap-row', !formal && 'has-action')}
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
          {!formal && (
            <button
              type="button"
              className="ap-row-action"
              title="复制到任务正式成果（原件保留，覆盖自动留恢复点）"
              onClick={(e) => {
                e.stopPropagation()
                setPromoteTarget(a)
              }}
            >
              转正
            </button>
          )}
          <span className={cn('ap-status', formal ? 'baseline' : a.promotion_proposed ? 'pending' : 'regen')}>
            {formal ? '任务基线' : a.promotion_proposed ? '待转正' : '仅本会话'}
          </span>
        </span>
      </div>
    )
  }

  // 解析去重：每个源文件只列一行主稿（<stem>.md），源文件夹层不再展开
  const parseRows: WorkbenchFile[] = []
  {
    const parseFiles = workbench.filter((f) => f.path.startsWith('parse/'))
    const seen = new Set<string>()
    for (const f of parseFiles) {
      const src = f.path.split('/')[1] ?? ''
      if (!src || seen.has(src)) continue
      seen.add(src)
      const main = parseFiles.find((p) => p.path === `parse/${src}/${src}.md`) ?? f
      parseRows.push(main)
    }
  }
  const analysisFiles = workbench.filter((f) => f.path.startsWith('analysis/'))
  const outlineRoots = workbench.filter((f) => f.path.startsWith('outline/') && !f.path.startsWith('outline/fragments/'))
  const fragments = workbench.filter((f) => f.path.startsWith('outline/fragments/'))

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
                // 窄态调列宽、宽态调整个浮层宽度（用户明令：展开态也能拖左缘调宽）
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
            <span className="ap-head-title">产物 · {currentTask?.title ?? '当前任务'}</span>
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
                  disabled={taskArtifacts.length === 0 && convArtifacts.length === 0}
                  onClick={() => {
                    const target = taskArtifacts[0] ?? convArtifacts[0]
                    if (target) onOpen(target.artifact_id)
                  }}
                >
                  <Maximize2 />
                </button>
              )}
            </div>
          </div>

          <div className="ap-body">
            {/* 任务正式成果 */}
            <div className="ap-group">
              <div className="ap-group-head">
                <span>任务正式成果</span>
                {taskArtifacts.length > 0 && <span className="ap-count">{taskArtifacts.length}</span>}
              </div>
              {loadingTask ? (
                <p className="ap-empty">加载中…</p>
              ) : taskArtifacts.length === 0 ? (
                <p className="ap-empty">
                  还没有任务正式成果。
                  <br />
                  会话产物经你确认后，会成为任务共享成果。
                </p>
              ) : (
                taskArtifacts.map(artifactRow)
              )}
            </div>

            {/* 本会话产物 */}
            <div className="ap-group">
              <div className="ap-group-head">
                <span>本会话产物</span>
                {convArtifacts.length > 0 && <span className="ap-count">{convArtifacts.length}</span>}
              </div>
              {loadingConv ? (
                <p className="ap-empty">加载中…</p>
              ) : convArtifacts.length === 0 ? (
                <p className="ap-empty">
                  本会话还没有产物。
                  <br />
                  Agent 生成目录、矩阵或笔记后，会显示在这里。
                </p>
              ) : (
                convArtifacts.map(artifactRow)
              )}
            </div>

            {/* 任务工作台：默认折叠一层 */}
            <div className="ap-group">
              <button type="button" className="ap-group-head clickable" onClick={() => setWbOpen((v) => !v)}>
                <span>任务工作台</span>
                {workbench.length > 0 && <span className="ap-count">{workbench.length}</span>}
                {wbOpen ? <ChevronDown className="ap-chev" /> : <ChevronRight className="ap-chev" />}
              </button>
              {wbOpen &&
                (loadingWorkbench ? (
                  <p className="ap-empty">加载中…</p>
                ) : workbench.length === 0 ? (
                  <p className="ap-empty">
                    尚未生成内容。
                    <br />
                    解析、分析或目录流程运行后，过程文件会显示在这里。
                  </p>
                ) : (
                  <div className="ap-wb">
                    {parseRows.length > 0 && (
                      <div className="ap-sub">
                        <div className="ap-sub-head">解析</div>
                        {parseRows.map((f) => wbRow(f, f.path.split('/')[1]))}
                      </div>
                    )}
                    {analysisFiles.length > 0 && (
                      <div className="ap-sub">
                        <div className="ap-sub-head">分析</div>
                        {analysisFiles.map((f) => wbRow(f))}
                      </div>
                    )}
                    {(outlineRoots.length > 0 || fragments.length > 0) && (
                      <div className="ap-sub">
                        <div className="ap-sub-head">目录</div>
                        {outlineRoots.map((f) => wbRow(f))}
                        {fragments.map((f) => {
                          const stem = (f.path.split('/').pop() ?? '').replace(/\.[^.]+$/, '')
                          return wbRow(f, `分册 · ${stem}`)
                        })}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          </div>
          </div>
          {wsOpen &&
            (workbenchPath ? (
              <WorkbenchViewer
                taskId={currentTask?.id ?? null}
                conversationId={currentConvId}
                path={workbenchPath}
              />
            ) : (
              <ArtifactOpenHost artifactId={previewId} />
            ))}
        </aside>
      </div>
      <PromoteConfirmModal artifact={promoteTarget} onClose={() => setPromoteTarget(null)} />
    </>
  )
}
