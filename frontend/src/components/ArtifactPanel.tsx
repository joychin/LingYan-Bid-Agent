import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, FileText, X } from 'lucide-react'
import type { Artifact, FileItem, Task, WorkbenchFile } from '@/api/client'
import { ErrorCard } from '@/components/ErrorCard'
import {
  fetchWorkbenchRaw,
  getWorkbenchContent,
  isTauri,
  revealInFolder,
  restoreArtifact,
} from '@/api/client'
import { useArtifactContent, useTaskArtifacts, useConversationArtifacts } from '@/hooks/useArtifacts'
import { useFiles } from '@/hooks/useFiles'
import { useWorkbench } from '@/hooks/useWorkbench'
import type { DirectoryData } from '@/components/processors/directoryTree'
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
import { FINAL_TAIL, wbDisplayName } from '@/lib/wbNames'
import { orderBodyRows } from '@/lib/workbenchTable'
import { cn, downloadBlob, downloadText, formatSize } from '@/lib/utils'

const DEFAULT_W = 300
const MIN_W = 240
const MAX_W = 560
/* 工作区覆盖态（.ap-shell.wide）宽度：与窄态列宽分开记忆；可拖面板左缘调节，
 * 上限动态计算给聊天区留 ≥360px（2026-09-09 用户明令：面板不设固定最大宽度）。
 * 默认宽按视口比例（60%）——小窗口自动少占聊天区、大屏不用手动拖宽；
 * 拖过的宽度存 localStorage，启动读回时同样过上限夹取（换小窗口打开不爆）。
 * 窗口缩放时实时重夹（resize 监听），否则先拖宽后缩窗面板会盖满聊天区。
 * 上限与窄态 navMaxW 同口径（侧栏按 264 估）：占位同宽修复（2026-09-23 N2）把
 * 覆盖式变真实让位后，只留 360 不扣侧栏会把聊天挤到 ~96px；默认值同样过 clamp，
 * 保证任何窗口下默认态聊天区 ≥360（视口 <1264 时 640 下限顶住、聊天收窄但完整可用）。 */
const WS_MIN_W = 640
const WS_WIDTH_KEY = 'tender-agent.ws-width'
const wsMaxW = () => Math.max(WS_MIN_W, window.innerWidth - 264 - 360)
const clampWsW = (w: number) => Math.max(WS_MIN_W, Math.min(wsMaxW(), w))
const wsDefaultW = () => clampWsW(Math.round(window.innerWidth * 0.6))
const wsStoredW = (): number => {
  const raw = Number(localStorage.getItem(WS_WIDTH_KEY))
  return Number.isFinite(raw) && raw >= WS_MIN_W ? raw : wsDefaultW()
}
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

// 整本-<册名>.docx=合册产出的最终交付物（行徽标/组内置顶/DocxView 交付提醒共用判定）
const isFinalDoc = (path: string) => (path.split('/').pop() ?? '').startsWith('整本-')

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
  onOpenLibrary,
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
  /** 跳素材库主视图（写作指引缺素材→检索建块闭环）；缺省不渲染入口 */
  onOpenLibrary?: () => void
}) {
  const {
    data: taskArtifacts = [],
    isLoading: loadingTask,
    isError: artifactsError,
    refetch: refetchArtifacts,
  } = useTaskArtifacts(currentTask?.id ?? null)
  const { data: convArtifacts = [] } = useConversationArtifacts(currentConvId)
  const {
    data: workbench = [],
    isLoading: loadingWorkbench,
    isError: workbenchError,
    refetch: refetchWorkbench,
  } = useWorkbench(currentTask?.id ?? null)
  const {
    data: sourceFiles = [],
    isLoading: loadingFiles,
    isError: filesError,
    refetch: refetchFiles,
  } = useFiles(currentTask?.id ?? null)
  const [width, setWidth] = useState(DEFAULT_W)
  const [wsWidth, setWsWidth] = useState(() => clampWsW(wsStoredW()))
  const [dragging, setDragging] = useState(false)
  const appRect = useRef<DOMRect | null>(null)
  // 行级右键菜单（fixed 浮层，与编辑器 Esc/点选互不干扰见 ContextMenu）
  const [menu, setMenu] = useState<{ x: number; y: number; target: RowMenuTarget } | null>(null)
  // 组折叠态（组头可点击；会话内记忆，与 NavSection 同纪律不进 localStorage）
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  // 正文章节子区默认收起：整本/指引/承诺常驻可见，几十个节文件不糊屏
  const [sectionsOpen, setSectionsOpen] = useState(false)
  // 目录中间稿（底稿+分册草稿）默认收起：目录产物常驻可见，草稿不糊屏
  const [draftsOpen, setDraftsOpen] = useState(false)
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const wsOpen = !collapsed && (!!previewId || !!workbenchPath || !!sourceFile)

  // 章序真值 = 目录产物树序（不是文件名序）；无目录/解析失败回退 null → 面板保持原序
  const dirArtifact = taskArtifacts.find((a) => a.kind === 'tender.directory')
  const { data: dirRaw } = useArtifactContent(dirArtifact?.artifact_id ?? null)
  const dirData = useMemo<DirectoryData | null>(() => {
    if (!dirRaw?.content) return null
    try {
      const parsed = JSON.parse(dirRaw.content) as DirectoryData
      return Array.isArray(parsed.response_documents) ? parsed : null
    } catch {
      return null
    }
  }, [dirRaw])

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

  /** docx 副本下载（整本交付物拿到本机打印/交标；复用版式预览的 raw 端点，文件不出本机）。 */
  const saveDocxCopy = async (f: WorkbenchFile) => {
    try {
      if (!currentTask) return
      downloadBlob(f.path.split('/').pop() ?? '未命名.docx', await fetchWorkbenchRaw(currentTask.id, f.path))
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
        ...(f.path.endsWith('.docx')
          ? [{ label: '下载副本', action: () => void saveDocxCopy(f) }]
          : []),
      ]
    }
    const a = t.artifact
    return [
      { label: '打开', action: () => onOpen(a.artifact_id) },
      ...(isTauri() ? [{ label: '打开文件夹', action: () => reveal(a.path) }] : []),
      // 磁盘绝对路径（与「打开文件夹」同源）——定位产物包用
      { label: '复制路径', action: () => void copyText(a.path, '路径') },
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

  // 窗口缩放时把面板宽重新夹进上限（聊天区 ≥360 兜底）：只夹不改语义——
  // 拖宽后再缩窗，面板若无此步会保持旧宽盖满聊天区甚至伸出窗口左缘
  useEffect(() => {
    const onResize = () => setWsWidth(clampWsW)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

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
  // 正文夹的整本标书产物（tender.volume，合册发布）：有产物行时工作台的同名整本
  // 文件不再重复出第二行（同一内容；产物行带预览/下载）。旧任务无产物时维持文件行。
  const volumeArtifacts = taskArtifacts.filter((a) => a.kind === 'tender.volume')

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

  const artifactRow = (a: Artifact, tail?: string) => {
    const fromConv = convArtifactIds.has(a.artifact_id)
    const icon = kindIcon(a.kind)
    const final = tail === FINAL_TAIL
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
        {tail && (
          <span className="ap-row-tail">
            <span
              className={cn('ap-status', !final && 'regen')}
              style={
                final
                  ? {
                      color: 'var(--Color-brand-primary)',
                      background:
                        'color-mix(in srgb, var(--Color-brand-primary) 12%, var(--Color-bg-canvas))',
                    }
                  : undefined
              }
            >
              {tail}
            </span>
          </span>
        )}
      </div>
    )
  }

  const wbRow = (f: WorkbenchFile, name?: string, tailOverride?: string) => {
    // 图标按扩展名（.docx=W 徽章，与素材库/知识库同一色板族）
    const icon = fileExtIcon(f.path)
    const isFinal = isFinalDoc(f.path)
    const parts = f.path.split('/')
    // 多册节文件嵌套在 body/<册>/ 下——尾部显册名；平铺 docx 全组同质，不占徽章
    const volDir = parts.length > 2 ? parts[parts.length - 2] : ''
    const tail = isFinal
      ? FINAL_TAIL
      : (tailOverride ??
        (f.editable
          ? '可编辑'
          : f.path.endsWith('.docx')
            ? volDir
            : '解析只读'))
    return (
      <div
        key={f.path}
        className="ap-row compact"
        onClick={() => onOpenWorkbench(f.path)}
        title={f.path}
        onContextMenu={(e) => openMenu(e, { kind: 'workbench', file: f })}
      >
        <span className={cn('ft-ico', icon.cls)}>{icon.mark}</span>
        <span className="ap-row-name truncate">{name ?? wbDisplayName(f.path)}</span>
        <span className="ap-row-tail">
          {tail && (
            <span
              className={cn('ap-status', !isFinal && 'regen')}
              style={
                isFinal
                  ? {
                      color: 'var(--Color-brand-primary)',
                      background:
                        'color-mix(in srgb, var(--Color-brand-primary) 12%, var(--Color-bg-canvas))',
                    }
                  : undefined
              }
            >
              {tail}
            </span>
          )}
        </span>
      </div>
    )
  }

  const loading = loadingTask || loadingWorkbench || loadingFiles
  // 失败 ≠ 空态（2026-09-17 批次⑤）：任一清单拉取失败给可重试错误卡，不伪装成
  // 「任务还没有文件」——那会诱导用户以为产出丢了
  const listError = artifactsError || workbenchError || filesError
  const refetchLists = () => {
    void refetchArtifacts()
    void refetchWorkbench()
    void refetchFiles()
  }

  return (
    <div
      className={cn('ap-slot', collapsed && 'collapsed', dragging && 'dragging')}
      // 占位与浮层同宽（含工作区覆盖态）：占位仍是 300 时宽面板向左盖住聊天区右侧
      // 564px——发送钮/模型胶囊被浮层拦截不可点也不可见（2026-09-23 自动化测试 N2）。
      // 占位同步后聊天列（含输入区）整体让位，宽态拖动/窗口重夹逻辑原样生效
      style={collapsed ? undefined : { width: wsOpen ? wsWidth : width }}
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
              let last = wsWidth
              const onMove = (ev: MouseEvent) => {
                if (!appRect.current) return
                const next = appRect.current.right - ev.clientX
                if (wsOpen) {
                  last = clampWsW(next)
                  setWsWidth(last)
                } else setWidth(Math.max(MIN_W, Math.min(navMaxW(), next)))
              }
              const onUp = () => {
                setDragging(false)
                if (wsOpen) localStorage.setItem(WS_WIDTH_KEY, String(last))
                window.removeEventListener('mousemove', onMove)
                window.removeEventListener('mouseup', onUp)
              }
              window.addEventListener('mousemove', onMove)
              window.addEventListener('mouseup', onUp)
            }}
          />
          <div className="ap-head">
            <span className="ap-head-title">任务文件 · {currentTask?.title ?? '当前任务'}</span>
          </div>
          {/* 宽态编辑器收起钮（2026-09-09 三态切换重构：右上角两个钮各管一段——
              这个 X 只管「回文件列表」，钉角开关只管「隐藏面板」；Esc 同义。
              让位注记见各编辑器头部 88px 右 padding） */}
          {wsOpen && (
            <button
              type="button"
              className="ap-editor-close"
              title="收起编辑器，回到文件列表（Esc）"
              onClick={onClearPreview}
            >
              <X />
            </button>
          )}

          <div className="ap-body">
            {loading ? (
              <div className="ap-empty flex items-center gap-1.5">
                <Loader variant="classic" size="sm" tone="muted" />
                加载中…
              </div>
            ) : listError ? (
              <div className="ap-empty">
                <ErrorCard
                  message="文件清单加载失败，已生成的文件不会丢。"
                  code={null}
                  retryText="重试"
                  onRetry={refetchLists}
                />
              </div>
            ) : taskArtifacts.length === 0 && workbench.length === 0 && sourceFiles.length === 0 ? (
              <p className="ap-empty">
                任务还没有文件。
                <br />
                AI 解析、分析、生成目录或笔记后，会显示在这里。
              </p>
            ) : (
              GROUPS.map((g) => {
                const rows: ReactNode[] = []
                // 文件计数（组头徽章）：章节子区算 N 不算 1
                let count = 0
                const pushRow = (node: ReactNode) => {
                  rows.push(node)
                  count += 1
                }
                // 产物
                if (g.key === 'outline') {
                  directoryArtifacts.forEach((a) => pushRow(artifactRow(a)))
                } else if (g.key === 'note') {
                  noteArtifacts.forEach((a) => pushRow(artifactRow(a)))
                }
                // 输入文件（只读行）与过程文件
                if (g.key === 'sources') sourceFiles.forEach((f) => pushRow(sourceRow(f)))
                else if (g.key === 'parse') parseRows.forEach((f) => pushRow(wbRow(f)))
                else if (g.key === 'analysis') analysisFiles.forEach((f) => pushRow(wbRow(f)))
                else if (g.key === 'outline') {
                  // 底稿/分册收进默认折叠的「中间稿」子区（正文组「章节 · 中间稿」同款交互）
                  if (outlineFiles.length > 0 || fragmentFiles.length > 0) {
                    // 底稿 mtime 更新 = 分册内容已并入（mtime 可靠侧先例；合并后又改分册则自动失效恢复「可编辑」）
                    const worksheet = outlineFiles.find((f) => f.path === 'outline/tender-response-docs.md')
                    const mergedInto = (f: WorkbenchFile) =>
                      !!worksheet && new Date(worksheet.mtime).getTime() > new Date(f.mtime).getTime()
                    rows.push(
                      <div className={cn('ap-sub', !draftsOpen && 'collapsed')} key="ap-outline-drafts">
                        <button
                          type="button"
                          className="ap-sub-head"
                          onClick={() => setDraftsOpen((v) => !v)}
                        >
                          <span>中间稿</span>
                          <span className="ap-count">{outlineFiles.length + fragmentFiles.length}</span>
                          <ChevronDown className="ap-chev" />
                        </button>
                        {draftsOpen && (
                          <>
                            {outlineFiles.map((f) => wbRow(f))}
                            {fragmentFiles.map((f) =>
                              wbRow(f, undefined, mergedInto(f) ? '已并入' : undefined),
                            )}
                          </>
                        )}
                      </div>,
                    )
                    count += outlineFiles.length + fragmentFiles.length
                  }
                } else if (g.key === 'body') {
                  // 整本标书产物（tender.volume，合册发布）置组首——交付物有产物身份
                  // （聊天卡/预览/下载），册序按目录树；有产物行时工作台的同名整本
                  // 文件行不再重复出（旧任务无产物时维持文件行，重跑合册即有产物）
                  const volNames = (dirData?.response_documents ?? []).map((d) => d.name)
                  const volRank = (a: Artifact) => {
                    const i = volNames.indexOf(a.display_name)
                    return i >= 0 ? i : volNames.length
                  }
                  ;volumeArtifacts
                    .toSorted((x, y) => volRank(x) - volRank(y))
                    .forEach((a) => {
                      pushRow(artifactRow(a, FINAL_TAIL))
                    })
                  const hideFinalRows = volumeArtifacts.length > 0
                  // 整本=最终交付物排组首（册序）；节文件按目录树序；无目录回退列表原序
                  const ordered = orderBodyRows(bodyFiles.map((f) => f.path), dirData)
                  const byPath = new Map(bodyFiles.map((f) => [f.path, f]))
                  const rowOf = (p: string | null) => (p ? byPath.get(p) : undefined)
                  if (!hideFinalRows) {
                    ordered.finals.forEach((p) => {
                      const f = rowOf(p)
                      if (f) pushRow(wbRow(f))
                    })
                  }
                  const guideF = rowOf(ordered.guide)
                  if (guideF) pushRow(wbRow(guideF))
                  const promiseF = rowOf(ordered.promise)
                  if (promiseF) pushRow(wbRow(promiseF))
                  if (ordered.sections.length > 0) {
                    // 章节中间稿默认收进折叠区（默认收起）——整本/指引/承诺常驻可见
                    const sectionFiles = ordered.sections
                      .map((p) => byPath.get(p))
                      .filter((f): f is WorkbenchFile => !!f)
                    rows.push(
                      <div className={cn('ap-sub', !sectionsOpen && 'collapsed')} key="ap-body-sections">
                        <button
                          type="button"
                          className="ap-sub-head"
                          onClick={() => setSectionsOpen((v) => !v)}
                        >
                          <span>章节 · 中间稿</span>
                          <span className="ap-count">{sectionFiles.length}</span>
                          <ChevronDown className="ap-chev" />
                        </button>
                        {sectionsOpen && sectionFiles.map((f) => wbRow(f))}
                      </div>,
                    )
                    count += sectionFiles.length
                  }
                }

                if (rows.length === 0) return null
                const collapsedG = !!collapsedGroups[g.key]
                return (
                  <div className={cn('ap-group', collapsedG && 'collapsed')} key={g.key}>
                    <button
                      type="button"
                      className="ap-group-head clickable"
                      onClick={() => setCollapsedGroups((m) => ({ ...m, [g.key]: !m[g.key] }))}
                    >
                      <span>{g.label}</span>
                      {count > 0 && <span className="ap-count">{count}</span>}
                      <ChevronDown className="ap-chev" />
                    </button>
                    {!collapsedG && rows}
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
                  onOpenLibrary={onOpenLibrary}
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
