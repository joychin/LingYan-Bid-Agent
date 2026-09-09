/**
 * 「写作指引」专用视图：`| 节 | 模式 | 依据 | 素材 | 缺口/备注 |` 五列结构化表格。
 *
 * 看得懂：依据编号 chips 点开看招标原文（目录产物 registry，同目录树来源徽章一套）；
 * 素材块 chips 点开看块内容（素材库现有接口）；【缺】/块失效/同块多派/节不在目录
 * 显示级提示；状态列「已写」点击直达该节正文文件。改得动：模式下拉切换（inline
 * toggle chips）、单元格编辑、按目录叶子加行（选择而非手输——节名须与目录逐字
 * 一致）、删行两步确认。保存写回同一 md 文件（useTableFile 全链），AI 后续按改后
 * 的指引执行（sidecar 三个消费方现读文件即生效）。
 */

import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, ListPlus, TriangleAlert } from 'lucide-react'
import type { MtBlock } from '@/api/client'
import { getWorkbenchContent } from '@/api/client'
import { useTaskArtifacts, useArtifactContent } from '@/hooks/useArtifacts'
import { useWorkbench } from '@/hooks/useWorkbench'
import { useMtBlocks, useMtBlockContent } from '@/hooks/useKnowledge'
import { cn } from '@/lib/utils'
import { Dialog } from '@/components/ui/dialog'
import { MarkdownEditor, type EditorMode } from '@/components/editors/MarkdownEditor'
import { SourceEntryCard, SourceTraceDialog, type SourceEntry } from '@/components/processors/SourceTraceDialog'
import { BadgeLegend, badgeStyle } from '@/components/processors/DirectoryProcessor'
import type { DirectoryData } from '@/components/processors/directoryTree'
import { guideRowBasis, parseEvaluationScores, scoreValueBadge, type RowBasis, type ScoreRow } from '@/lib/guideBasis'
import { CellPicker } from './CellPicker'
import { FileEditorShell } from './FileEditorShell'
import { CellInput, CellText, RowDelete, SourceFallbackNotice } from './tableBits'
import { useTableFile } from './useTableFile'
import {
  GUIDE_MODES,
  GUIDE_TABLE,
  guideRowFlags,
  guideRowMatches,
  iterLeaves,
  leafGroups,
  leafKey,
  multiVolume,
  normRefId,
  parseBlockRefs,
  parseModeTokens,
  parseRefIds,
  sortRefIds,
  writtenPathOf,
  writtenSections,
  type DirLeaf,
  type GuideFilterKey,
} from '@/lib/workbenchTable'

/** 无需正文文件的交付形态（body_contract.NON_PROSE_DELIVERY 同款）——加行默认模式「—」。 */
const NON_PROSE_DELIVERY = ['模板或附件填充', '目录容器']

const isKnownMode = (t: string) => (GUIDE_MODES as readonly string[]).includes(t)

/** 查看态两级分组视图（view useMemo 产物）：一级章节组（direct=顶层直挂行）+ 二级子组。 */
interface GuideSubGroup {
  label: string
  /** 折叠键（复合 `${top}/${sub}`，foldedGroups 共用一池） */
  key: string
  rows: number[]
}
interface GuideTopGroup {
  label: string
  key: string
  count: number
  direct: number[]
  subs: GuideSubGroup[]
}
type GuideGroupList = GuideTopGroup[] | null

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

  // 目录产物（当前任务单一版本）：依据溯源 registry + 加行叶子对账
  const { data: taskArtifacts } = useTaskArtifacts(taskId)
  const dirArtifact = taskArtifacts?.find((a) => a.kind === 'tender.directory') ?? null
  const { data: dirRaw } = useArtifactContent(dirArtifact?.artifact_id ?? null)
  const dir = useMemo(() => {
    if (!dirRaw) return null
    try {
      const data = JSON.parse(dirRaw.content) as DirectoryData
      const docs = data.response_documents ?? []
      if (!docs.length) return null
      const leaves = iterLeaves(docs)
      const multi = multiVolume(docs)
      return {
        registry: data.registry ?? {},
        leaves,
        multi,
        docs,
        topMap: leafGroups(docs, multi),
        leafKeys: new Set(leaves.map((l) => leafKey(l.vol, l.title, multi))),
      }
    } catch {
      return null
    }
  }, [dirRaw])

  // 素材块映射（chips 标题 + 弹窗元数据）；已写节映射（状态徽章）
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

  // 评分表（analysis/evaluation.md）→ SCORE 分值/评分要点。registry 不存分值，
  // SCORE 编号=表体行序（assemble_tender 同构）。文件缺失/未跑分析 → 空 Map 降级
  //（分值角标不显示，定性计数照常——前缀计数不依赖评分表）。与 workbench 内容
  // 查询同 key 前缀，共享缓存与失效。
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

  // 查看态过滤 + 一级章节分组（设计稿 D）+ 行展开（F）；编辑态恒全量平铺——行索引直通 setCell
  const [filter, setFilter] = useState<GuideFilterKey>('all')
  const [foldedGroups, setFoldedGroups] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<number | null>(null)
  useEffect(() => {
    if (file.editing) {
      setFilter('all')
      setExpanded(null)
    }
  }, [file.editing])
  useEffect(() => setExpanded(null), [filter])

  const validBlockIds = useMemo(() => new Set(blockMap.keys()), [blockMap])
  const rowFlags = useMemo(
    () =>
      file.rows.map((r) =>
        guideRowFlags(r[0] ?? '', r[3] ?? '', {
          validBlockIds,
          leafKeys: dir?.leafKeys ?? null,
          written: writtenPathOf(r[0] ?? '', written, dir?.multi ?? false) !== undefined,
        }),
      ),
    [file.rows, validBlockIds, dir, written],
  )
  const filterCounts = useMemo(() => {
    const c: Record<GuideFilterKey, number> = {
      all: file.rows.length,
      missing: 0,
      stale: 0,
      offtree: 0,
      todo: 0,
      written: 0,
    }
    for (const f of rowFlags) {
      if (f.missing) c.missing += 1
      if (f.stale) c.stale += 1
      if (f.offtree) c.offtree += 1
      if (f.written) c.written += 1
      else c.todo += 1
    }
    return c
  }, [rowFlags, file.rows.length])

  // 过滤后视图：分组（目录树一级章节，组序=行序首现；单组/无树不分）+ 行原索引
  // 过滤后视图：两级分组（目录树一级章节大组 + 大章内的二级章节子组，组序=行序
  // 首现）+ 行原索引。二级分组治「大章 35 行平铺、内部层级不可见」。
  const view = useMemo(() => {
    const idxs = file.rows.map((_r, i) => i).filter((i) => guideRowMatches(rowFlags[i], filter))
    const gmap = dir?.topMap ?? null
    if (!gmap) return { groups: null as GuideGroupList, idxs }
    const tops: GuideTopGroup[] = []
    const topIdx = new Map<string, GuideTopGroup>()
    for (const i of idxs) {
      const cell = file.rows[i][0] ?? ''
      const g = gmap.get(cell) ?? { top: '未分组', second: null }
      const topLabel = dir?.multi && cell.includes('/') ? `${cell.split('/')[0].trim()} · ${g.top}` : g.top
      let t = topIdx.get(topLabel)
      if (!t) {
        t = { label: topLabel, key: topLabel, count: 0, direct: [], subs: [] }
        topIdx.set(topLabel, t)
        tops.push(t)
      }
      if (g.second) {
        const subLabel = g.second
        let s = t.subs.find((x) => x.label === subLabel)
        if (!s) {
          s = { label: subLabel, key: `${topLabel}/${subLabel}`, rows: [] }
          t.subs.push(s)
        }
        s.rows.push(i)
      } else {
        t.direct.push(i)
      }
    }
    for (const t of tops) t.count = t.direct.length + t.subs.reduce((n, s) => n + s.rows.length, 0)
    if (tops.length <= 1 && (tops[0]?.subs.length ?? 0) === 0) return { groups: null, idxs }
    return { groups: tops, idxs }
  }, [file.rows, rowFlags, filter, dir])

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

  const setCell = (row: number, col: number, v: string) => {
    file.applyRows(file.rows.map((r, i) => (i === row ? r.map((c, k) => (k === col ? v : c)) : r)))
  }

  const addLeafRow = (l: DirLeaf) => {
    const key = leafKey(l.vol, l.title, dir?.multi ?? false)
    const mode = NON_PROSE_DELIVERY.includes(l.delivery) ? '—' : '推理撰写'
    file.applyRows([...file.rows, [key, mode, '—', '—', '—']])
  }

  /** 溯源「查看原文上下文」：出处 L 行号 → 招标文件解析 md 只读定位（DirectoryProcessor 同款）。 */
  /** 溯源「查看原文上下文」已改为条目内嵌切片（ParseContextBlock，2026-09-09
   *  用户拍板就地展示替代跳转）——本函数无消费方，删除。 */

  const missingCount = filterCounts.missing
  const usedKeys = new Set(file.rows.map((r) => r[0] ?? ''))

  /** 表格行（查看/编辑共用，i=行原索引——编辑态 setCell 直通）。 */
  const rowView = (r: string[], i: number) => {
    const sectionCell = r[0] ?? ''
    const inTree = !dir || dir.leafKeys.has(sectionCell)
    const wPath = writtenPathOf(sectionCell, written, dir?.multi ?? false)
    const refs = parseRefIds(r[2] ?? '')
    const mat = parseBlockRefs(r[3] ?? '')
    const basis = rowBases[i]
    const isOpen = expanded === i
    // 节列查看态瘦身：多册键剥册名前缀（分组头已表达册），悬停 title 保留全名；
    // 编辑态/无分组（无目录）显示原文——数据层始终是完整键。
    const sectionDisplay =
      file.editing || !view.groups || !(dir?.multi && sectionCell.includes('/'))
        ? sectionCell
        : sectionCell.slice(sectionCell.indexOf('/') + 1).trim()
    return (
      <Fragment key={i}>
      <tr className="border-b border-line/60 align-top hover:bg-muted/30">
        {/* 节列锁定：须与目录逐字一致，改名走目录产物或重新生成指引。
            查看态点节名展开本节依据详情（F）——只挂节列，行内其他可点元素不受牵连。 */}
        <td
          className={cn('px-2 py-1.5 font-medium', !file.editing && 'cursor-pointer')}
          title={inTree ? (file.editing ? undefined : '点开查看本节依据详情（为什么写这章、值多少分）') : '不在目录叶子中——节名须与目录逐字一致（目录改版后须重对指引）'}
          onClick={file.editing ? undefined : () => setExpanded(isOpen ? null : i)}
        >
          <div className="flex items-start gap-1">
            {!file.editing &&
              (isOpen ? (
                <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-3" />
              ) : (
                <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-3" />
              ))}
            <span className="break-words leading-relaxed" title={sectionCell}>
              {sectionDisplay}
            </span>
            {!inTree && <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />}
          </div>
        </td>
        <td className="px-2 py-1.5">
          {file.editing ? (
            <ModeToggles value={r[1] ?? ''} onChange={(v) => setCell(i, 1, v)} />
          ) : (
            <ModeBadges tokens={parseModeTokens(r[1] ?? '')} />
          )}
        </td>
        <td className="px-2 py-1.5">
          {file.editing ? (
            <RefCellEditor
              value={r[2] ?? ''}
              onChange={(v) => setCell(i, 2, v)}
              registry={(dir?.registry ?? null) as Record<string, SourceEntry> | null}
              scores={scores}
            />
          ) : (
            <div className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-1">
                {refs.ids.map((id) => (
                  <RefChip
                    key={id}
                    id={id}
                    badge={basis.badges.get(id)}
                    traceable={dir !== null}
                    known={dir ? id in dir.registry : false}
                    onClick={() => setTraceId(id)}
                  />
                ))}
                {refs.rest && <span className="break-words text-xs text-ink-3">{refs.rest}</span>}
                {refs.ids.length === 0 && !refs.rest && <CellText value="—" />}
              </div>
              {/* H · 定性摘要行：不用点开就知道这章为什么写、有多重要 */}
              {basis.stance && (
                <p className="text-xs leading-relaxed text-ink-3">
                  <span className="mr-1 rounded-full bg-warning/15 px-1.5 py-px font-medium text-warning">{basis.stance}</span>
                  {basis.summaryLine}
                </p>
              )}
            </div>
          )}
        </td>
        <td className="px-2 py-1.5">
          {file.editing ? (
            <MaterialCellEditor
              value={r[3] ?? ''}
              onChange={(v) => setCell(i, 3, v)}
              blockMap={blockMap}
              usage={blockUsage}
              onOpenBlock={setBlockDlg}
              onOpenLibrary={onOpenLibrary}
            />
          ) : (
            <div className="flex flex-wrap items-center gap-1">
              {mat.blockIds.map((id) => (
                <BlockChip
                  key={id}
                  id={id}
                  block={blockMap.get(id)}
                  usage={blockUsage.get(id) ?? 1}
                  onOpen={() => {
                    const b = blockMap.get(id)
                    if (b) setBlockDlg(b)
                  }}
                />
              ))}
              {mat.missing && (
                <span
                  title="缺素材——AI 会写【待补】并在收尾点名，可先去素材库检索建块"
                  className="shrink-0 rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning"
                >
                  缺
                </span>
              )}
              {mat.rest && <span className="break-words text-xs text-ink-3">{mat.rest}</span>}
              {mat.blockIds.length === 0 && !mat.missing && !mat.rest && <CellText value="—" />}
            </div>
          )}
        </td>
        <td className="px-2 py-1.5">
          {file.editing ? (
            <CellInput value={r[4] ?? ''} onChange={(v) => setCell(i, 4, v)} placeholder="缺口/备注（可空）" />
          ) : (
            <CellText value={r[4] ?? ''} />
          )}
        </td>
        <td className="px-2 py-1.5">
          {wPath ? (
            <button
              type="button"
              onClick={() => onOpenWorkbench(wPath)}
              title="打开该节正文文件"
              className="rounded-full bg-success-soft px-2 py-0.5 text-xs text-success hover:underline"
            >
              已写
            </button>
          ) : (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-ink-3">待写</span>
          )}
        </td>
        {file.editing && (
          <td className="px-2 py-1.5">
            <RowDelete
              hint="删行后该节回到「指引缺行」状态（AI 按权重 1 兜底派发或提示缺行）"
              onConfirm={() => file.applyRows(file.rows.filter((_r, j) => j !== i))}
            />
          </td>
        )}
      </tr>
      {/* F · 行展开：本节依据详情（定性 + 逐条原文/分值/评分要点/出处 + 原文上下文切片） */}
      {!file.editing && isOpen && (
        <tr className="border-b border-line/60 bg-muted/30">
          <td colSpan={6} className="px-4 py-3">
            <GuideRowPanel
              row={r}
              basis={basis}
              registry={(dir?.registry ?? null) as Record<string, SourceEntry> | null}
              scores={scores}
              taskId={taskId}
              onTrace={(id) => setTraceId(id)}
            />
          </td>
        </tr>
      )}
      </Fragment>
    )
  }

  /** 查看态分组头（目录一级章节；可折叠，折叠只藏行、头常驻）。 */
  /** 分组折叠开关（foldedGroups 按 key：一级=key、二级=`一级/二级` 复合键）。 */
  const toggleFold = (key: string) =>
    setFoldedGroups((s) => {
      const next = new Set(s)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  /** 一级章节大组头（册名·章节名 + 节数；左侧品牌色条强区分）。 */
  const topHeaderRow = (g: { label: string; key: string; count: number }) => {
    const folded = foldedGroups.has(g.key)
    return (
      <tr key={`g-${g.key}`} className="bg-muted/50">
        <td colSpan={6} className="px-2 py-2">
          <button
            type="button"
            onClick={() => toggleFold(g.key)}
            className="flex items-center gap-1.5 border-l-2 border-primary/60 pl-2 text-[13px] font-semibold text-ink"
          >
            {folded ? <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" /> : <ChevronDown className="h-4 w-4 shrink-0 text-ink-3" />}
            <span className="text-left">{g.label}</span>
            <span className="shrink-0 text-xs font-normal text-ink-3">共 {g.count} 节</span>
          </button>
        </td>
      </tr>
    )
  }

  /** 二级章节子组头（大章内部层级；缩进+更轻，chevron 同视觉语言）。 */
  const subHeaderRow = (g: { label: string; key: string; rows: number[] }) => {
    const folded = foldedGroups.has(g.key)
    return (
      <tr key={`g-${g.key}`} className="bg-muted/20">
        <td colSpan={6} className="px-2 py-1">
          <button
            type="button"
            onClick={() => toggleFold(g.key)}
            className="flex items-center gap-1 pl-7 text-xs font-medium text-ink-2"
          >
            {folded ? <ChevronRight className="h-3 w-3 shrink-0 text-ink-3" /> : <ChevronDown className="h-3 w-3 shrink-0 text-ink-3" />}
            <span className="text-left">{g.label}</span>
            <span className="shrink-0 font-normal text-ink-3">{g.rows.length} 节</span>
          </button>
        </td>
      </tr>
    )
  }

  return (
    <FileEditorShell
      title="写作指引"
      file={file}
      badges={
        missingCount > 0 ? (
          file.editing || !file.tableMode ? (
            <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">缺素材 {missingCount} 节</span>
          ) : (
            <button
              type="button"
              onClick={() => setFilter('missing')}
              title="点此只看缺素材的节"
              className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning hover:underline"
            >
              缺素材 {missingCount} 节
            </button>
          )
        ) : undefined
      }
      notice={!file.tableMode ? <SourceFallbackNotice what="「节｜模式｜依据｜素材｜缺口/备注」" /> : undefined}
    >
      {file.tableMode ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <p className="shrink-0 text-xs leading-relaxed text-muted-foreground">
            每节一行：模式=怎么写（素材修订/格式跟随/推理撰写，可组合）；依据=呼应的招标要求（评分类带分值；点节名展开看逐条原文与出处）；
            素材=使用的素材块（点开看内容，「缺」=待补素材）；「—」=非正文节点（模板填充/附件）。
            改动保存后，AI 按改后的指引执行。
          </p>
          <div className="shrink-0">
            <BadgeLegend />
          </div>
          {!file.editing && file.rows.length > 0 && (
            <FilterPills value={filter} counts={filterCounts} onChange={setFilter} />
          )}
          <table className="w-full min-w-[900px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line-2 text-left text-xs text-muted-foreground">
                <th className="min-w-[200px] px-2 py-2 font-medium">节</th>
                <th className="w-[210px] px-2 py-2 font-medium">模式</th>
                <th className="w-[150px] px-2 py-2 font-medium">依据</th>
                <th className="w-[200px] px-2 py-2 font-medium">素材</th>
                <th className="min-w-[150px] px-2 py-2 font-medium">缺口/备注</th>
                <th className="w-[64px] px-2 py-2 font-medium">状态</th>
                {file.editing && <th className="w-24 px-2 py-2 font-medium">操作</th>}
              </tr>
            </thead>
            <tbody>
              {(file.editing
                ? file.rows.map((r, i) => rowView(r, i))
                : view.groups
                  ? view.groups.flatMap((g) => {
                      if (foldedGroups.has(g.key)) return [topHeaderRow(g)]
                      return [
                        topHeaderRow(g),
                        ...g.direct.map((idx) => rowView(file.rows[idx], idx)),
                        ...g.subs.flatMap((s) =>
                          foldedGroups.has(s.key)
                            ? [subHeaderRow(s)]
                            : [subHeaderRow(s), ...s.rows.map((idx) => rowView(file.rows[idx], idx))],
                        ),
                      ]
                    })
                  : view.idxs.map((idx) => rowView(file.rows[idx], idx))
              )}
              {file.rows.length === 0 && (
                <tr>
                  <td colSpan={6 + (file.editing ? 1 : 0)} className="px-2 py-6 text-center text-xs text-muted-foreground">
                    指引还没有行——{dir ? '从下方「从目录添加节行」选择要写的节' : '无目录产物，等待 AI 生成指引'}。
                  </td>
                </tr>
              )}
              {!file.editing && file.rows.length > 0 && view.idxs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-2 py-6 text-center text-xs text-muted-foreground">
                    该筛选没有命中行——切换其他筛选或点「全部」。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {file.editing &&
            (dir ? (
              <LeafPicker leaves={dir.leaves} usedKeys={usedKeys} multi={dir.multi} onPick={addLeafRow} />
            ) : (
              <p className="text-xs text-ink-3">无目录产物——不能对账节名，暂不能手动加行（可让 AI 重新生成指引）。</p>
            ))}
        </div>
      ) : file.editing ? (
        <MarkdownEditor value={file.text} onChange={file.editSource} mode={editorMode} onModeChange={setEditorMode} />
      ) : (
        <MarkdownEditor value={file.text} mode="preview" viewOnly className="prose-sm" />
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

// ---------- 单元格小组件 ----------

/** 查看态模式徽章：合法 token 中性、「—」弱化、未知 token 警示（validate_body issue 的显示级前哨）。 */
function ModeBadges({ tokens }: { tokens: string[] }) {
  if (tokens.length === 0 || tokens[0] === '—') return <span className="text-ink-3">—</span>
  return (
    <div className="flex flex-wrap gap-1">
      {tokens.map((t) => (
        <span
          key={t}
          title={isKnownMode(t) ? undefined : `未知模式「${t}」——合法值：素材修订/格式跟随/推理撰写（「+」组合；非正文节点写「—」）`}
          className={cn('rounded-full px-2 py-0.5 text-xs', isKnownMode(t) ? 'bg-muted text-ink-2' : 'bg-warning/15 text-warning')}
        >
          {t}
        </span>
      ))}
    </div>
  )
}

/** 模式 toggle chip 的两态样式（ModeToggles 专用，模块层避免每次渲染重建）。 */
function modeChipClass(on: boolean) {
  return cn(
    'rounded-full border px-2 py-0.5 text-xs',
    on ? 'border-primary bg-accent-soft text-primary' : 'border-line text-muted-foreground hover:border-primary',
  )
}

/** 编辑态模式切换：三模式 toggle chips（顺序固定、「+」组合）+「—」独占项（非正文节点）。 */
function ModeToggles({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const tokens = parseModeTokens(value)
  const active = new Set(tokens.filter(isKnownMode))
  const none = tokens.length === 0 || tokens[0] === '—'
  const toggle = (m: (typeof GUIDE_MODES)[number]) => {
    const next = new Set(active)
    if (next.has(m)) next.delete(m)
    else next.add(m)
    onChange(GUIDE_MODES.filter((x) => next.has(x)).join('+') || '—')
  }
  return (
    <div className="flex flex-wrap gap-1">
      {GUIDE_MODES.map((m) => (
        <button key={m} type="button" onClick={() => toggle(m)} className={modeChipClass(active.has(m))}>
          {m}
        </button>
      ))}
      <button type="button" onClick={() => onChange('—')} title="非正文节点（模板填充/附件）" className={modeChipClass(none)}>
        —
      </button>
    </div>
  )
}

/** 依据编号 chip：四色同目录树来源徽章；评分类带分值角标（SCORE-07 · 10分）；
 *  点开=登记表原文+出处溯源。 */
function RefChip({
  id,
  badge,
  traceable,
  known,
  onClick,
}: {
  id: string
  badge?: string
  traceable: boolean
  known: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={!traceable}
      onClick={onClick}
      title={traceable ? (known ? '点开查看招标原文与出处' : '登记表中没有该编号（引用悬空）') : '目录产物缺失，暂无法溯源'}
      style={badgeStyle(id)}
      className="shrink-0 rounded px-1.5 py-px text-xs font-medium hover:underline disabled:no-underline"
    >
      {id}
      {badge && <span className="ml-1 opacity-80">{badge}</span>}
    </button>
  )
}

/** F · 行展开面板：本节依据详情（为什么写这章）——定性徽章+摘要行，
 *  逐条「编号 chip + 分值/评分要点 + 登记原文 + 原文上下文切片」；悬空与
 *  无依据机械兜底。上下文切片内嵌在条目卡片（ParseContextBlock）。 */
function GuideRowPanel({
  row,
  basis,
  registry,
  scores,
  taskId,
  onTrace,
}: {
  row: string[]
  basis: RowBasis
  registry: Record<string, SourceEntry> | null
  scores: Map<string, ScoreRow>
  taskId: string | null
  onTrace: (id: string) => void
}) {
  const ids = parseRefIds(row[2] ?? '').ids
  return (
    <div className="flex flex-col gap-3 border-l-2 border-primary/40 pl-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {basis.stance && (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 font-medium text-warning">{basis.stance}</span>
        )}
        <span className="text-ink-3">{basis.summaryLine ?? '本节无登记依据'}</span>
      </div>
      {ids.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          本节没有关联登记编号——按模式与招标格式件写作（模板填充/附件类，或补依据后重新生成指引）。
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {ids.map((id) => {
            const entry = registry?.[id]
            const score = scores.get(id)
            return (
              <div key={id} className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => onTrace(id)}
                    style={badgeStyle(id)}
                    className="shrink-0 rounded px-1.5 py-px text-xs font-medium hover:underline"
                  >
                    {id}
                  </button>
                  {score && (
                    <span className="shrink-0 rounded-full bg-warning/15 px-2 py-px text-xs font-medium text-warning">
                      分值 {score.value}
                    </span>
                  )}
                  {score?.points && (
                    <span className="min-w-0 truncate text-xs text-ink-3" title={score.points}>
                      评分要点：{score.points}
                    </span>
                  )}
                </div>
                {entry ? (
                  <SourceEntryCard entry={entry} taskId={taskId} />
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {registry === null
                      ? '目录产物缺失，暂无法展示该条详情。'
                      : `登记表中没有 ${id} 的条目（引用悬空）——可能是指引手改引入的编号。`}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/** 素材块 chip：标题（失效=已删除警示；同块多派=警示 tint——一块只派一节）。 */
function BlockChip({
  id,
  block,
  usage,
  onOpen,
}: {
  id: string
  block: MtBlock | undefined
  usage: number
  onOpen: () => void
}) {
  if (!block) {
    return (
      <span
        title="素材块已删除——重检索并更新指引"
        className="shrink-0 rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning"
      >
        {id} · 已删除
      </span>
    )
  }
  const dup = usage > 1
  return (
    <button
      type="button"
      onClick={onOpen}
      title={dup ? `该块同时派给 ${usage} 节——一块只派一节（同块多派=正文逐字重复）` : '点开查看素材块内容'}
      className={cn(
        'max-w-full shrink-0 truncate rounded-full px-2 py-0.5 text-xs font-medium hover:underline',
        dup ? 'bg-warning/15 text-warning' : 'bg-muted text-ink-2',
      )}
    >
      {block.title || id}
    </button>
  )
}

/** 编辑态素材列的解析预览（块标题/失效/【缺】即时反馈；有效块可点开看内容——改素材时正需要看）。 */
function MatPreview({
  cell,
  blockMap,
  usage,
  onOpen,
}: {
  cell: string
  blockMap: Map<string, MtBlock>
  usage: Map<string, number>
  onOpen?: (b: MtBlock) => void
}) {
  const m = parseBlockRefs(cell)
  if (!m.blockIds.length && !m.missing && !m.rest) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
      {m.blockIds.map((id) => {
        const b = blockMap.get(id)
        const dup = (usage.get(id) ?? 1) > 1
        const cls = cn(
          'max-w-full truncate rounded-full px-1.5 py-px',
          !b || dup ? 'bg-warning/15 text-warning' : 'bg-muted text-ink-2',
        )
        const label = b ? b.title || id : `${id} 已删除`
        const title = !b ? '素材块已删除' : dup ? '该块同时派给多节——一块只派一节' : '点开查看素材块内容'
        return b && onOpen ? (
          <button key={id} type="button" onClick={() => onOpen(b)} title={title} className={cn(cls, 'hover:underline')}>
            {label}
          </button>
        ) : (
          <span key={id} className={cls} title={title}>
            {label}
          </span>
        )
      })}
      {m.missing && <span className="rounded-full bg-warning/15 px-1.5 py-px text-warning">缺</span>}
      {m.rest && <span className="text-ink-3">{m.rest}</span>}
    </div>
  )
}

/** 素材块内容弹窗：元数据 + 分节切片（素材库现有接口）。 */
function BlockDialog({ block, onClose }: { block: MtBlock | null; onClose: () => void }) {
  const { data: content, isLoading } = useMtBlockContent(block?.id ?? null, block !== null)
  if (!block) return null
  return (
    <Dialog open onClose={onClose} title={`素材块 · ${block.title || block.id}`}>
      <div className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>来源文件：{block.file_name ?? '—'}</span>
          {block.chars ? <span>{block.chars} 字</span> : null}
          {(block.ranges ?? []).length > 0 && (
            <span>区间 {(block.ranges ?? []).map(([s, e]) => `L${s}-L${e}`).join('、')}</span>
          )}
        </div>
        {block.note && (
          <p className="rounded-lg border border-line bg-muted/40 px-3 py-2 text-xs leading-relaxed">{block.note}</p>
        )}
        <div className="max-h-64 overflow-auto rounded-lg border border-line">
          {isLoading ? (
            <p className="p-3 text-xs text-muted-foreground">加载块内容…</p>
          ) : (
            (content?.sections ?? []).map((s, i) => (
              <div key={i} className="border-b border-line/60 px-3 py-2 last:border-b-0">
                <div className="mb-1 text-xs text-muted-foreground">L{s.start}-L{s.end}</div>
                <p className="whitespace-pre-wrap text-xs leading-relaxed">{s.text}</p>
              </div>
            ))
          )}
          {!isLoading && (content?.sections ?? []).length === 0 && (
            <p className="p-3 text-xs text-muted-foreground">（块内容为空）</p>
          )}
        </div>
        <p className="text-xs text-ink-3">块 id 只在素材库当前块表内稳定——删块后指引里的引用会失效，需重检索更新。</p>
      </div>
    </Dialog>
  )
}

/** 加行选择器：目录叶子（排除已有行）按册分组——选择而非手输，消灭「节名对不上账」。 */
function LeafPicker({
  leaves,
  usedKeys,
  multi,
  onPick,
}: {
  leaves: DirLeaf[]
  usedKeys: Set<string>
  multi: boolean
  onPick: (leaf: DirLeaf) => void
}) {
  const [open, setOpen] = useState(false)
  const remaining = useMemo(() => leaves.filter((l) => !usedKeys.has(leafKey(l.vol, l.title, multi))), [leaves, usedKeys, multi])
  const byVol = useMemo(() => {
    const m = new Map<string, DirLeaf[]>()
    for (const l of remaining) {
      const arr = m.get(l.vol) ?? []
      arr.push(l)
      m.set(l.vol, arr)
    }
    return [...m.entries()]
  }, [remaining])
  return (
    <div className="shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-fit rounded-md border border-line px-3 py-1.5 text-xs text-muted-foreground hover:border-primary hover:text-foreground"
      >
        {open ? '收起目录叶子' : `+ 从目录添加节行${remaining.length ? `（${remaining.length} 个待加）` : ''}`}
      </button>
      {open && (
        <div
          className="mt-2 max-h-72 overflow-auto rounded-lg border border-line p-2"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              setOpen(false)
            }
          }}
        >
          {byVol.length === 0 ? (
            <p className="p-2 text-xs text-muted-foreground">目录叶子都已在本指引中有行。</p>
          ) : (
            byVol.map(([vol, items]) => (
              <div key={vol} className="mb-2 last:mb-0">
                <div className="px-1 py-1 text-xs font-medium text-muted-foreground">{vol}</div>
                {items.map((l) => (
                  <button
                    key={`${l.vol}/${l.title}`}
                    type="button"
                    onClick={() => {
                      onPick(l)
                      setOpen(false)
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                  >
                    <span className="min-w-0 flex-1 truncate">{l.title}</span>
                    <span className="shrink-0 text-xs text-ink-3">{l.delivery || '未标注形态'}</span>
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ---------- 查看态过滤胶囊（设计稿 D） ----------

const FILTER_PILLS: { key: GuideFilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'missing', label: '缺素材' },
  { key: 'stale', label: '块失效' },
  { key: 'offtree', label: '不在目录' },
  { key: 'todo', label: '待写' },
  { key: 'written', label: '已写' },
]

const PILL_TINT: Record<Exclude<GuideFilterKey, 'all'>, string> = {
  missing: 'bg-warning/15 text-warning',
  stale: 'bg-warning/15 text-warning',
  offtree: 'bg-warning/15 text-warning',
  todo: 'bg-muted text-ink-3',
  written: 'bg-success-soft text-success',
}

function pillClass(key: GuideFilterKey, active: boolean): string {
  if (key === 'all') return active ? 'bg-inverse text-primary-foreground' : 'bg-muted text-ink-2 hover:text-foreground'
  const ring = !active
    ? ''
    : key === 'written'
      ? ' ring-1 ring-inset ring-success'
      : key === 'todo'
        ? ' ring-1 ring-inset ring-ink-3'
        : ' ring-1 ring-inset ring-warning'
  return PILL_TINT[key] + ring
}

/** 查看态过滤胶囊：单选、0 行禁用——警示一击可达，不用在长表里扫黄点。 */
function FilterPills({
  value,
  counts,
  onChange,
}: {
  value: GuideFilterKey
  counts: Record<GuideFilterKey, number>
  onChange: (k: GuideFilterKey) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {FILTER_PILLS.map(({ key, label }) => {
        const n = counts[key]
        const active = value === key
        const disabled = key !== 'all' && n === 0
        return (
          <button
            key={key}
            type="button"
            disabled={disabled}
            onClick={() => onChange(key)}
            title={disabled ? `${label}：没有行` : `只看「${label}」（${n} 行）`}
            className={cn('rounded-full px-2.5 py-1 text-xs', pillClass(key, active), disabled && 'cursor-default opacity-40')}
          >
            {label} {n}
          </button>
        )
      })}
    </div>
  )
}

// ---------- 编辑态单元格选择器（设计稿 A） ----------

/** 素材列编辑：输入框保留手输/粘贴自由度，右侧按钮开选择浮层——搜标题/来源、
 * 点选即插入归一化 id、已选再点移除；浮层内自带字数与来源，选块不再抄 blk_id。 */
function MaterialCellEditor({
  value,
  onChange,
  blockMap,
  usage,
  onOpenBlock,
  onOpenLibrary,
}: {
  value: string
  onChange: (v: string) => void
  blockMap: Map<string, MtBlock>
  usage: Map<string, number>
  onOpenBlock: (b: MtBlock) => void
  onOpenLibrary?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)

  const ids = parseBlockRefs(value).blockIds
  const toggle = (id: string) => {
    const next = ids.includes(id) ? value.replace(id, ' ') : `${value.trim()} ${id}`
    onChange(next.replace(/\s{2,}/g, ' ').trim() || '—')
  }

  const ql = q.trim().toLowerCase()
  const shown = [...blockMap.values()].filter(
    (b) => !ql || (b.title || b.id).toLowerCase().includes(ql) || (b.file_name ?? '').toLowerCase().includes(ql),
  )
  const LIMIT = 50

  return (
    <div>
      <div ref={wrapRef} className="flex items-start gap-1">
        <CellInput value={value} onChange={onChange} placeholder="blk_…、【缺】，或点右侧选择" className="flex-1" />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          title="从素材库选择素材块"
          className={cn(
            'mt-px flex shrink-0 items-center rounded-md border px-1.5 py-1 text-xs',
            open
              ? 'border-primary text-primary'
              : 'border-line text-muted-foreground hover:border-primary hover:text-foreground',
          )}
        >
          <ListPlus className="h-3.5 w-3.5" />
        </button>
      </div>
      <MatPreview cell={value} blockMap={blockMap} usage={usage} onOpen={onOpenBlock} />
      {open && wrapRef.current && (
        <CellPicker anchor={wrapRef.current} onClose={() => setOpen(false)} width={340}>
          <div className="border-b border-line px-2 pb-1.5 pt-1">
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索素材块（标题 / 来源文件）"
              className="w-full rounded-md border border-line bg-background px-2 py-1 text-xs outline-none focus:border-primary"
            />
          </div>
          <div className="max-h-72 overflow-auto py-0.5">
            {shown.length === 0 ? (
              <div className="px-3 py-3 text-center text-xs text-muted-foreground">
                没有匹配的素材块
                {onOpenLibrary && (
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false)
                      onOpenLibrary()
                    }}
                    className="mt-2 block w-full rounded-md border border-line px-2 py-1.5 text-muted-foreground hover:border-primary hover:text-foreground"
                  >
                    去素材库检索建块
                  </button>
                )}
              </div>
            ) : (
              <>
                {shown.slice(0, LIMIT).map((b) => {
                  const sel = ids.includes(b.id)
                  const dup = (usage.get(b.id) ?? 1) > 1
                  return (
                    <button
                      key={b.id}
                      type="button"
                      onClick={() => toggle(b.id)}
                      title={dup ? '该块已派给多节——一块只派一节' : sel ? '点击从本行移除' : '点击加入本行'}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted',
                        sel && 'bg-accent-soft',
                      )}
                    >
                      <span
                        className={cn(
                          'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                          sel ? 'border-primary bg-primary text-primary-foreground' : 'border-line',
                        )}
                      >
                        {sel && <Check className="h-3 w-3" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-foreground">{b.title || b.id}</span>
                        <span className="block truncate text-xs text-ink-3">
                          {b.chars ? `${b.chars} 字 · ` : ''}
                          {b.file_name || '未知来源'}
                        </span>
                      </span>
                    </button>
                  )
                })}
                {shown.length > LIMIT && (
                  <p className="px-3 py-1.5 text-center text-xs text-ink-3">还有 {shown.length - LIMIT} 个——继续输入筛选</p>
                )}
              </>
            )}
          </div>
        </CellPicker>
      )}
    </div>
  )
}

/** 依据列编辑：输入框 + 登记表选择浮层——列目录产物全部条目（四色编号+原文摘录），
 * 点选插入归一化编号、再点移除；无目录产物时按钮禁用（仍可手输）。 */
function RefCellEditor({
  value,
  onChange,
  registry,
  scores,
}: {
  value: string
  onChange: (v: string) => void
  registry: Record<string, SourceEntry> | null
  scores: Map<string, ScoreRow>
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)

  const ids = parseRefIds(value).ids
  const toggle = (rawId: string) => {
    const id = normRefId(rawId)
    const next = ids.includes(id) ? value.replace(id, ' ') : `${value.trim()} ${id}`
    onChange(next.replace(/\s{2,}/g, ' ').trim() || '—')
  }

  const ql = q.trim().toLowerCase()
  const shown = sortRefIds(Object.keys(registry ?? {})).filter((id) => {
    if (!ql) return true
    const entry = registry?.[id] as SourceEntry | undefined
    return id.toLowerCase().includes(ql) || (entry?.text ?? '').toLowerCase().includes(ql)
  })
  const LIMIT = 50

  return (
    <div>
      <div ref={wrapRef} className="flex items-start gap-1">
        <CellInput value={value} onChange={onChange} placeholder="如 REQ-01、SCORE-02" className="flex-1" />
        <button
          type="button"
          disabled={!registry}
          onClick={() => setOpen((v) => !v)}
          title={registry ? '从目录登记表选择依据' : '目录产物缺失，暂不能从登记表选择（可手输编号）'}
          className={cn(
            'mt-px flex shrink-0 items-center rounded-md border px-1.5 py-1 text-xs',
            !registry && 'cursor-default opacity-40',
            open
              ? 'border-primary text-primary'
              : 'border-line text-muted-foreground hover:border-primary hover:text-foreground',
          )}
        >
          <ListPlus className="h-3.5 w-3.5" />
        </button>
      </div>
      {open && registry && wrapRef.current && (
        <CellPicker anchor={wrapRef.current} onClose={() => setOpen(false)} width={360}>
          <div className="border-b border-line px-2 pb-1.5 pt-1">
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索编号 / 要求原文"
              className="w-full rounded-md border border-line bg-background px-2 py-1 text-xs outline-none focus:border-primary"
            />
          </div>
          <div className="max-h-72 overflow-auto py-0.5">
            {shown.length === 0 ? (
              <p className="px-3 py-3 text-center text-xs text-muted-foreground">没有匹配的登记条目</p>
            ) : (
              <>
                {shown.slice(0, LIMIT).map((id) => {
                  const entry = registry[id] as SourceEntry | undefined
                  const sel = ids.includes(id)
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => toggle(id)}
                      title={sel ? '点击从本行移除' : '点击加入本行'}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted',
                        sel && 'bg-accent-soft',
                      )}
                    >
                      <span style={badgeStyle(id)} className="shrink-0 rounded px-1.5 py-px text-xs font-medium">
                        {id}
                      </span>
                      {(() => {
                        const sv = scores.get(id)
                        return sv ? (
                          <span className="shrink-0 rounded-full bg-warning/15 px-1.5 py-px text-xs font-medium text-warning">
                            {scoreValueBadge(sv.value) ?? sv.value}
                          </span>
                        ) : null
                      })()}
                      <span className="min-w-0 flex-1 truncate text-xs text-ink-2">
                        {entry?.text || entry?.出处 || '（登记表未存原文）'}
                      </span>
                      {sel && <Check className="h-3.5 w-3.5 shrink-0 text-primary" />}
                    </button>
                  )
                })}
                {shown.length > LIMIT && (
                  <p className="px-3 py-1.5 text-center text-xs text-ink-3">还有 {shown.length - LIMIT} 条——继续输入筛选</p>
                )}
              </>
            )}
          </div>
        </CellPicker>
      )}
    </div>
  )
}
