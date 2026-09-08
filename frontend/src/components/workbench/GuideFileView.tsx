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

import { useEffect, useMemo, useState } from 'react'
import { TriangleAlert } from 'lucide-react'
import type { MtBlock } from '@/api/client'
import { useTaskArtifacts, useArtifactContent } from '@/hooks/useArtifacts'
import { useWorkbench } from '@/hooks/useWorkbench'
import { useMtBlocks, useMtBlockContent } from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { cn } from '@/lib/utils'
import { Dialog } from '@/components/ui/dialog'
import { MarkdownEditor, type EditorMode } from '@/components/editors/MarkdownEditor'
import { SourceTraceDialog, type SourceEntry } from '@/components/processors/SourceTraceDialog'
import { badgeStyle } from '@/components/processors/DirectoryProcessor'
import type { DirectoryData } from '@/components/processors/directoryTree'
import { FileEditorShell } from './FileEditorShell'
import { CellInput, CellText, RowDelete, SourceFallbackNotice } from './tableBits'
import { useTableFile } from './useTableFile'
import {
  GUIDE_MODES,
  GUIDE_TABLE,
  iterLeaves,
  leafKey,
  multiVolume,
  parseBlockRefs,
  parseModeTokens,
  parseRefIds,
  writtenPathOf,
  writtenSections,
  type DirLeaf,
} from '@/lib/workbenchTable'

/** 无需正文文件的交付形态（body_contract.NON_PROSE_DELIVERY 同款）——加行默认模式「—」。 */
const NON_PROSE_DELIVERY = ['模板或附件填充', '目录容器']

const isKnownMode = (t: string) => (GUIDE_MODES as readonly string[]).includes(t)

export function GuideFileView({
  taskId,
  path,
  onOpenWorkbench,
}: {
  taskId: string | null
  path: string | null
  onOpenWorkbench: (path: string, anchorLine?: number) => void
}) {
  const file = useTableFile({ taskId, path, spec: GUIDE_TABLE })
  const { toast } = useToast()
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

  // 溯源弹窗（依据=登记表原文；素材=块内容）
  const [traceId, setTraceId] = useState<string | null>(null)
  const [blockDlg, setBlockDlg] = useState<MtBlock | null>(null)

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
  const openSourceContext = async (_id: string, entry: { 出处?: string }) => {
    const m = entry.出处?.match(/L(\d+)/)
    const line = m ? Number(m[1]) : undefined
    const parseFile = (wbFiles ?? []).find((f) => f.path.startsWith('parse/'))
    if (!parseFile) {
      toast('未找到已解析的原文（work/parse/ 为空）', 'error')
      return
    }
    setTraceId(null)
    onOpenWorkbench(parseFile.path, line)
  }

  const missingCount = file.rows.filter((r) => parseBlockRefs(r[3] ?? '').missing).length
  const usedKeys = new Set(file.rows.map((r) => r[0] ?? ''))

  return (
    <FileEditorShell
      title="写作指引"
      file={file}
      badges={
        missingCount > 0 ? (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">缺素材 {missingCount} 节</span>
        ) : undefined
      }
      notice={!file.tableMode ? <SourceFallbackNotice what="「节｜模式｜依据｜素材｜缺口/备注」" /> : undefined}
    >
      {file.tableMode ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <p className="shrink-0 text-xs leading-relaxed text-muted-foreground">
            每节一行：模式=怎么写（素材修订/格式跟随/推理撰写，可组合）；依据=呼应的招标要求（点开看原文与出处）；
            素材=使用的素材块（点开看内容，「缺」=待补素材）；「—」=非正文节点（模板填充/附件）。
            改动保存后，AI 按改后的指引执行。
          </p>
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
              {file.rows.map((r, i) => {
                const sectionCell = r[0] ?? ''
                const inTree = !dir || dir.leafKeys.has(sectionCell)
                const wPath = writtenPathOf(sectionCell, written, dir?.multi ?? false)
                const refs = parseRefIds(r[2] ?? '')
                const mat = parseBlockRefs(r[3] ?? '')
                return (
                  <tr key={i} className="border-b border-line/60 align-top hover:bg-muted/30">
                    {/* 节列锁定：须与目录逐字一致，改名走目录产物或重新生成指引 */}
                    <td className="px-2 py-1.5 font-medium" title={inTree ? undefined : '不在目录叶子中——节名须与目录逐字一致（目录改版后须重对指引）'}>
                      <div className="flex items-start gap-1">
                        <span className="break-words leading-relaxed">{sectionCell}</span>
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
                        <CellInput value={r[2] ?? ''} onChange={(v) => setCell(i, 2, v)} placeholder="如 REQ-01、SCORE-02" />
                      ) : (
                        <div className="flex flex-wrap items-center gap-1">
                          {refs.ids.map((id) => (
                            <RefChip
                              key={id}
                              id={id}
                              traceable={dir !== null}
                              known={dir ? id in dir.registry : false}
                              onClick={() => setTraceId(id)}
                            />
                          ))}
                          {refs.rest && <span className="break-words text-xs text-ink-3">{refs.rest}</span>}
                          {refs.ids.length === 0 && !refs.rest && <CellText value="—" />}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-1.5">
                      {file.editing ? (
                        <div>
                          <CellInput value={r[3] ?? ''} onChange={(v) => setCell(i, 3, v)} placeholder="素材块 id（blk_…）或【缺】" />
                          <MatPreview cell={r[3] ?? ''} blockMap={blockMap} usage={blockUsage} />
                        </div>
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
                )
              })}
              {file.rows.length === 0 && (
                <tr>
                  <td colSpan={6 + (file.editing ? 1 : 0)} className="px-2 py-6 text-center text-xs text-muted-foreground">
                    指引还没有行——{dir ? '从下方「从目录添加节行」选择要写的节' : '无目录产物，等待 AI 生成指引'}。
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
        onOpenSource={(_id, e) => void openSourceContext(_id, e)}
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

/** 依据编号 chip：四色同目录树来源徽章；点开=登记表原文+出处溯源。 */
function RefChip({ id, traceable, known, onClick }: { id: string; traceable: boolean; known: boolean; onClick: () => void }) {
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
    </button>
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

/** 编辑态素材列的解析预览（块标题/失效/【缺】即时反馈）。 */
function MatPreview({ cell, blockMap, usage }: { cell: string; blockMap: Map<string, MtBlock>; usage: Map<string, number> }) {
  const m = parseBlockRefs(cell)
  if (!m.blockIds.length && !m.missing && !m.rest) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs">
      {m.blockIds.map((id) => {
        const b = blockMap.get(id)
        const dup = (usage.get(id) ?? 1) > 1
        return (
          <span
            key={id}
            className={cn(
              'max-w-full truncate rounded-full px-1.5 py-px',
              !b ? 'bg-warning/15 text-warning' : dup ? 'bg-warning/15 text-warning' : 'bg-muted text-ink-2',
            )}
            title={!b ? '素材块已删除' : dup ? '该块同时派给多节——一块只派一节' : undefined}
          >
            {b ? b.title || id : `${id} 已删除`}
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
