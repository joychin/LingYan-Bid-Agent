/**
 * 「写作指引」专用视图：左树右详情的两栏结构（2026-09-13 重构，取代原五列表格）。
 *
 * 左栏=目录真实层级的章节树（含「未分配」=目录有节点但指引没给行、「不在目录」=
 * 指引有行但目录里找不到），配搜索与筛选胶囊；右栏=选中节点的作业单（查看态）或
 * 表单（编辑态）。两栏都把「写什么/依据/素材」摆在同一处，不必再点开行展开。
 *
 * 文件格式零改动：编辑仍走 useTableFile + serializeTableFile，写回的还是同一张
 * `| 节 | 模式 | 依据 | 素材 | 缺口/备注 |` md 表——sidecar 三个消费方
 * （validate_body / assemble_tender / tender-body skill）现读即生效。
 * 本文件只做数据加载、筛选/状态判定与选中态编排；渲染在 GuideTree / GuideDetail。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import type { MtBlock } from '@/api/client'
import { getMtBlockContent, getWorkbenchContent } from '@/api/client'
import { useTaskArtifacts, useArtifactContent } from '@/hooks/useArtifacts'
import { useWorkbench } from '@/hooks/useWorkbench'
import { useMtBlocks } from '@/hooks/useKnowledge'
import { MarkdownEditor, type EditorMode } from '@/components/editors/MarkdownEditor'
import { SourceTraceDialog, type SourceEntry } from '@/components/processors/SourceTraceDialog'
import type { DirectoryData } from '@/components/processors/directoryTree'
import { parseEvaluationScores, guideRowBasis, type RowBasis, type ScoreRow } from '@/lib/guideBasis'
import { guideTree, offTreeRowsOf, type GuideTreeNode, type GuideTreeFilter } from '@/lib/guideTree'
import {
  GUIDE_TABLE,
  blockPreviewText,
  guideRowFlags,
  iterLeaves,
  leafKey,
  multiVolume,
  parseBlockRefs,
  writtenPathOf,
  writtenSections,
  type DirLeaf,
} from '@/lib/workbenchTable'
import { FileEditorShell } from './FileEditorShell'
import { BlockDialog } from './guideBits'
import { SourceFallbackNotice } from './tableBits'
import { GuideTree, type GuideNodeStatus } from './GuideTree'
import { GuideDetail } from './GuideDetail'
import { useTableFile } from './useTableFile'

/** 无需正文文件的交付形态（body_contract.NON_PROSE_DELIVERY 同款）——加行默认模式「—」。 */
const NON_PROSE_DELIVERY = ['模板或附件填充', '目录容器']

/** 源文件模式兜底说明（说明当前是 Markdown 源码，不是两栏视图）。 */
const SOURCE_NOTICE = '「节｜模式｜依据｜素材｜缺口/备注」'

/** 按 key 找树节点（选中态复原与详情取数共用）。 */
function findNode(nodes: GuideTreeNode[], key: string | null): GuideTreeNode | null {
  if (!key) return null
  for (const n of nodes) {
    if (n.key === key) return n
    const hit = findNode(n.children, key)
    if (hit) return hit
  }
  return null
}

/** 首个叶子节点（默认选中：没有已选时落在第一节，避免右栏空着）。 */
function firstLeaf(nodes: GuideTreeNode[]): GuideTreeNode | null {
  for (const n of nodes) {
    if (n.children.length) {
      const hit = firstLeaf(n.children)
      if (hit) return hit
    } else return n
  }
  return null
}

export function GuideFileView({
  taskId,
  path,
  onOpenWorkbench,
  onOpenLibrary,
}: {
  taskId: string | null
  path: string | null
  onOpenWorkbench: (path: string, anchorLine?: number) => void
  /** 跳素材库（缺素材→检索建块闭环的出口）；缺省不渲染入口 */
  onOpenLibrary?: () => void
}) {
  const file = useTableFile({ taskId, path, spec: GUIDE_TABLE })
  const [editorMode, setEditorMode] = useState<EditorMode>('split')

  // 目录产物（当前任务单一版本）：树层级 + 依据溯源 registry
  const { data: taskArtifacts } = useTaskArtifacts(taskId)
  const dirArtifact = taskArtifacts?.find((a) => a.kind === 'tender.directory') ?? null
  const { data: dirRaw } = useArtifactContent(dirArtifact?.artifact_id ?? null)
  const dir = useMemo(() => {
    if (!dirRaw) return null
    try {
      const data = JSON.parse(dirRaw.content) as DirectoryData
      const docs = data.response_documents ?? []
      if (!docs.length) return null
      return {
        registry: data.registry ?? {},
        leaves: iterLeaves(docs),
        multi: multiVolume(docs),
        docs,
      }
    } catch {
      return null
    }
  }, [dirRaw])

  // 素材块映射（chip 标题 + 弹窗元数据）；已写节映射（状态徽章）
  const { data: mtData } = useMtBlocks()
  const blockMap = useMemo(() => new Map((mtData?.blocks ?? []).map((b) => [b.id, b])), [mtData])
  const { data: wbFiles } = useWorkbench(taskId)
  const written = useMemo(
    () => writtenSections((wbFiles ?? []).map((f) => f.path), dir?.multi ?? false),
    [wbFiles, dir],
  )

  // 同块多派统计（validate_body「一块只派一节」issue 的显示级前哨）
  const blockUsage = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of file.rows) {
      for (const id of parseBlockRefs(r[3] ?? '').blockIds) m.set(id, (m.get(id) ?? 0) + 1)
    }
    return m
  }, [file.rows])

  // 素材底稿预览：本表引用的全部块 id → 块首段文本。走服务端截断形态（preview
  // 预算 = 显示 120 字 + 余量）；独立 key（block-preview）与块详情弹窗的全量缓存
  // （block-content）互不挤占。单块失败静默降级，staleTime 防重开面板反复拉。
  const PREVIEW_CHARS = 120
  const guideBlockIds = useMemo(() => {
    const s = new Set<string>()
    for (const r of file.rows) for (const id of parseBlockRefs(r[3] ?? '').blockIds) s.add(id)
    return [...s]
  }, [file.rows])
  const previewQueries = useQueries({
    queries: useMemo(
      () =>
        guideBlockIds.map((id) => ({
          queryKey: ['mt', 'block-preview', id] as const,
          queryFn: () => getMtBlockContent(id, PREVIEW_CHARS + 40),
          staleTime: 60_000,
          retry: false,
        })),
      [guideBlockIds],
    ),
  })
  const blockPreviews = useMemo(() => {
    const m = new Map<string, { preview: string; chars: number }>()
    for (const q of previewQueries) {
      if (q.data) m.set(q.data.id, { preview: blockPreviewText(q.data.sections, PREVIEW_CHARS), chars: q.data.chars })
    }
    return m
  }, [previewQueries, guideBlockIds])

  // 评分表（analysis/evaluation.md）→ SCORE 分值/评分要点。registry 不存分值，
  // SCORE 编号=表体行序（assemble_tender 同构）。文件缺失/未跑分析 → 空 Map 降级。
  const { data: evalRaw } = useQuery({
    queryKey: ['workbench', taskId, 'content', 'analysis/evaluation.md'],
    queryFn: async () => await getWorkbenchContent(taskId!, 'analysis/evaluation.md'),
    enabled: !!taskId,
    retry: false,
  })
  const scores = useMemo<Map<string, ScoreRow>>(
    () => (evalRaw ? parseEvaluationScores(evalRaw.content) : new Map()),
    [evalRaw],
  )
  const rowBases = useMemo<RowBasis[]>(() => file.rows.map((r) => guideRowBasis(r[2] ?? '', scores)), [file.rows, scores])

  // 溯源弹窗（依据=登记表原文；素材=块内容）
  const [traceId, setTraceId] = useState<string | null>(null)
  const [blockDlg, setBlockDlg] = useState<MtBlock | null>(null)

  const [filter, setFilter] = useState<GuideTreeFilter>('all')
  useEffect(() => {
    if (file.editing) setFilter('all')
  }, [file.editing])

  const validBlockIds = useMemo(() => new Set(blockMap.keys()), [blockMap])
  // 目录叶子键集合（单一来源：行旗帜、「不在目录」行、树选择合法键共用一份）——
  // null=无目录产物（降级平坦行），与 guideRowFlags 的 `leafKeys !== null` 守卫同口径。
  const leafKeys = useMemo(
    () => (dir ? new Set(dir.leaves.map((l) => leafKey(l.vol, l.title, dir.multi))) : null),
    [dir],
  )
  const rowFlags = useMemo(
    () =>
      file.rows.map((r) =>
        guideRowFlags(r[0] ?? '', r[3] ?? '', {
          validBlockIds,
          leafKeys,
          written: writtenPathOf(r[0] ?? '', written, dir?.multi ?? false) !== undefined,
        }),
      ),
    [file.rows, validBlockIds, leafKeys, dir, written],
  )

  // 导航树（目录真实层级；无目录产物回落平坦行列表）
  const tree = useMemo(() => guideTree(dir?.docs, file.rows, dir?.multi ?? false), [dir, file.rows])

  const statusOf = useCallback(
    (n: GuideTreeNode): GuideNodeStatus => {
      if (n.rowIndex < 0) return 'unassigned'
      const f = rowFlags[n.rowIndex]
      if (!f) return 'todo'
      if (f.missing || f.stale || f.offtree) return 'issue'
      return f.written ? 'written' : 'todo'
    },
    [rowFlags],
  )

  /** 筛选 + 搜索谓词。容器恒 false——靠 pruneTree 的「有命中后代则保留」规则留下，
   *  否则会留下空壳大章。 */
  const nodeMatches = useCallback(
    (n: GuideTreeNode): boolean => {
      if (n.children.length) return false
      const i = n.rowIndex
      if (i < 0) return filter === 'all' || filter === 'unassigned'
      const f = rowFlags[i]
      if (!f) return filter === 'all'
      switch (filter) {
        case 'missing':
          return f.missing
        case 'stale':
          return f.stale
        case 'offtree':
          return f.offtree
        case 'todo':
          return !f.written
        case 'written':
          return f.written
        default:
          return true
      }
    },
    [filter, rowFlags],
  )

  // 「不在目录」组：指引有行、树里挂不上（节名与目录叶子对不上）。按名判定，
  // 同名重复行同属一个叶子、不误报（与旧 GuideRowFlags.offtree 口径一致）；
  // 无目录产物（leafKeys=null）不判越界——否则降级平坦行会整组误标。
  const offTreeRows = useMemo(() => offTreeRowsOf(file.rows, leafKeys), [file.rows, leafKeys])

  // 胶囊计数：按树逐叶统计（与左栏实际显示严格一致，不另起一套口径）
  const counts = useMemo(() => {
    const c: Record<GuideTreeFilter, number> = {
      all: 0,
      missing: 0,
      unassigned: 0,
      stale: 0,
      offtree: offTreeRows.length,
      todo: 0,
      written: 0,
    }
    const walk = (list: GuideTreeNode[]) => {
      for (const n of list) {
        if (n.children.length) {
          walk(n.children)
          continue
        }
        c.all += 1
        const st = statusOf(n)
        if (st === 'unassigned') {
          c.unassigned += 1
          continue
        }
        const f = rowFlags[n.rowIndex]
        if (!f) continue
        if (f.missing) c.missing += 1
        if (f.stale) c.stale += 1
        if (f.written) c.written += 1
        else c.todo += 1
      }
    }
    walk(tree)
    c.all += offTreeRows.length
    return c
  }, [tree, rowFlags, offTreeRows, statusOf])

  // 选中节点（键=叶子 leafKey：删行后节点退回未分配态、选中不丢）
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const defaultKey = useMemo(() => firstLeaf(tree)?.key ?? null, [tree])
  // 「不在目录」行不在树上，按 label 合成一个节点参与解析——被点的行是真实
  // 行（rowIndex 有效），右栏查看/编辑落到它身上，而不是回落到首节；leaf=null
  // 使「加行」不误触发，statusOf 经 rowFlags[rowIndex].offtree 判为 issue。
  const offTreeNode = useMemo(() => {
    const hit = offTreeRows.find((x) => x.label === selectedKey)
    return hit
      ? ({ key: hit.label, label: hit.label, leaf: null, rowIndex: hit.rowIndex, children: [] } satisfies GuideTreeNode)
      : null
  }, [offTreeRows, selectedKey])
  useEffect(() => {
    if (!selectedKey || findNode(tree, selectedKey) || offTreeRows.some((x) => x.label === selectedKey)) return
    setSelectedKey(defaultKey)
  }, [tree, selectedKey, defaultKey, offTreeRows])
  const node = useMemo(
    () => findNode(tree, selectedKey) ?? offTreeNode ?? findNode(tree, defaultKey),
    [tree, selectedKey, defaultKey, offTreeNode],
  )

  const rowIndex = node?.rowIndex ?? -1
  const row = rowIndex >= 0 ? (file.rows[rowIndex] ?? null) : null

  const setCell = (col: number, v: string) => {
    if (rowIndex < 0) return
    file.applyRows(file.rows.map((r, i) => (i === rowIndex ? r.map((c, k) => (k === col ? v : c)) : r)))
  }

  const addLeafRow = (l: DirLeaf) => {
    const mode = NON_PROSE_DELIVERY.includes(l.delivery) ? '—' : '推理撰写'
    file.applyRows([...file.rows, [leafKey(l.vol, l.title, dir?.multi ?? false), mode, '—', '—', '—']])
  }

  const usedKeys = useMemo(() => new Set(file.rows.map((r) => r[0] ?? '')), [file.rows])

  // Esc 捕获段只关弹窗（stopPropagation 防止面板工作区一起收起）
  useEffect(() => {
    if (!traceId && !blockDlg) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      setTraceId(null)
      setBlockDlg(null)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [traceId, blockDlg])

  if (!path || !taskId) return null
  if (file.loading || (!file.text && file.loadError)) {
    return (
      <div className="ap-ws">
        <div className="ap-ws-body">
          <div className="p-6 text-center text-sm text-muted-foreground">
            {file.loading ? '加载工作台文件…' : `加载失败：${file.loadError}`}
          </div>
        </div>
      </div>
    )
  }

  return (
    <FileEditorShell
      title="写作指引"
      file={file}
      notice={!file.tableMode ? <SourceFallbackNotice what={SOURCE_NOTICE} /> : undefined}
      contentClassName="overflow-hidden"
    >
      {file.tableMode ? (
        <div className="flex min-h-0 flex-1">
          <GuideTree
            nodes={tree}
            selectedKey={node?.key ?? null}
            onSelect={setSelectedKey}
            filter={filter}
            onFilter={setFilter}
            counts={counts}
            statusOf={statusOf}
            matches={nodeMatches}
            offTreeRows={offTreeRows}
            editing={file.editing}
            leaves={dir?.leaves ?? []}
            usedKeys={usedKeys}
            multi={dir?.multi ?? false}
            onPickLeaf={addLeafRow}
          />
          <GuideDetail
            node={node}
            row={row}
            rowIndex={rowIndex}
            writtenPath={row ? writtenPathOf(row[0] ?? '', written, dir?.multi ?? false) : undefined}
            basis={row ? (rowBases[rowIndex] ?? null) : null}
            registry={(dir?.registry ?? null) as Record<string, SourceEntry> | null}
            scores={scores}
            blockMap={blockMap}
            blockPreviews={blockPreviews}
            blockUsage={blockUsage}
            taskId={taskId}
            editing={file.editing}
            status={node ? statusOf(node) : 'todo'}
            onTrace={setTraceId}
            onOpenBlock={setBlockDlg}
            onOpenWorkbench={onOpenWorkbench}
            onOpenLibrary={onOpenLibrary}
            onChangeCell={setCell}
            onAddRow={() => {
              if (node?.leaf) addLeafRow(node.leaf)
            }}
            onDeleteRow={() => {
              if (rowIndex >= 0) file.applyRows(file.rows.filter((_r, i) => i !== rowIndex))
            }}
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {file.editing ? (
            <MarkdownEditor value={file.text} onChange={file.editSource} mode={editorMode} onModeChange={setEditorMode} />
          ) : (
            <MarkdownEditor value={file.text} mode="preview" viewOnly className="prose-sm" />
          )}
        </div>
      )}

      <SourceTraceDialog
        traceId={traceId}
        entry={traceId ? (dir?.registry[traceId] as SourceEntry | undefined) : undefined}
        onClose={() => setTraceId(null)}
        taskId={taskId}
      />
      <BlockDialog block={blockDlg} onClose={() => setBlockDlg(null)} />
    </FileEditorShell>
  )
}
