/**
 * 写作指引的行内小组件（2026-09-13 两栏重构自 GuideFileView 原样搬出）：
 * 模式徽章/切换、依据与素材 chip、块内容弹窗、加行选择器、过滤胶囊、
 * 编辑态的依据/素材单元格选择器。语义与实现与搬迁前一致，仅 FilterPills
 * 增加「未分配」档（目录有节点、指引无行）。
 */

import { useMemo, useRef, useState } from 'react'
import { Check, ListPlus } from 'lucide-react'
import type { MtBlock } from '@/api/client'
import { useMtBlockContent } from '@/hooks/useKnowledge'
import { cn } from '@/lib/utils'
import { Dialog } from '@/components/ui/dialog'
import type { SourceEntry } from '@/components/processors/SourceTraceDialog'
import { badgeStyle } from '@/components/processors/DirectoryProcessor'
import { scoreValueBadge, type ScoreRow } from '@/lib/guideBasis'
import {
  GUIDE_MODES,
  leafKey,
  normRefId,
  parseBlockRefs,
  parseModeTokens,
  parseRefIds,
  sortRefIds,
  type DirLeaf,
} from '@/lib/workbenchTable'
import type { GuideTreeFilter } from '@/lib/guideTree'
import { CellInput, CellText, EMPTY_CELL, RowDelete } from './tableBits'
import { CellPicker } from './CellPicker'

const isKnownMode = (t: string) => (GUIDE_MODES as readonly string[]).includes(t)

/** 查看态模式徽章：合法 token 中性、「不写正文」弱化、未知 token 警示
 *  （validate_body issue 的显示级前哨）。 */
export function ModeBadges({ tokens }: { tokens: string[] }) {
  if (tokens.length === 0) return <span className="text-ink-3">—</span>
  if (tokens[0] === '—') return <span className="text-ink-3">不写正文</span>
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

/** 编辑态模式切换：三模式 toggle chips（顺序固定、「+」组合）+「不写正文」独占项
 *  （存储仍是「—」，非正文节点）。 */
export function ModeToggles({ value, onChange }: { value: string; onChange: (v: string) => void }) {
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
      <button
        type="button"
        onClick={() => onChange('—')}
        title="这一节不写正文：按招标原件填空或贴附件（投标函、授权书、身份证复印件这类），不走 AI 撰写"
        className={modeChipClass(none)}
      >
        不写正文
      </button>
    </div>
  )
}

/** 依据编号 chip：四色同目录树来源徽章；评分类带分值角标（SCORE-07 · 10分）；
 *  点开=登记表原文+出处溯源。 */
export function RefChip({
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

/** 素材块 chip：标题（失效=已删除警示；同块多派=警示 tint——一块只派一节）。 */
export function BlockChip({
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
export function MatPreview({
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
  // 「—」= 空值占位（无块也无缺料）——不再第二次显示这根横杠
  const rest = m.rest === '—' ? '' : m.rest
  if (!m.blockIds.length && !m.missing && !rest) return null
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
      {rest && <span className="text-ink-3">{rest}</span>}
    </div>
  )
}

/** 素材块内容弹窗：元数据 + 分节切片（素材库现有接口）。 */
export function BlockDialog({ block, onClose }: { block: MtBlock | null; onClose: () => void }) {
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
export function LeafPicker({
  leaves,
  usedKeys,
  multi,
  onPick,
}: {
  leaves: DirLeaf[]
  usedKeys: Set<string>
  multi: boolean
  onPick: (l: DirLeaf) => void
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

// ---------- 过滤胶囊 ----------

const FILTER_PILLS: { key: GuideTreeFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'missing', label: '缺素材' },
  { key: 'unassigned', label: '未分配' },
  { key: 'stale', label: '块失效' },
  { key: 'offtree', label: '不在目录' },
  { key: 'todo', label: '待写' },
  { key: 'written', label: '已写' },
]

const PILL_TINT: Record<Exclude<GuideTreeFilter, 'all'>, string> = {
  missing: 'bg-warning/15 text-warning',
  unassigned: 'bg-warning/15 text-warning',
  stale: 'bg-warning/15 text-warning',
  offtree: 'bg-warning/15 text-warning',
  todo: 'bg-muted text-ink-3',
  written: 'bg-success-soft text-success',
}

function pillClass(key: GuideTreeFilter, active: boolean): string {
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
export function FilterPills({
  value,
  counts,
  onChange,
}: {
  value: GuideTreeFilter
  counts: Record<GuideTreeFilter, number>
  onChange: (k: GuideTreeFilter) => void
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

// ---------- 编辑态单元格选择器 ----------

/** 素材列编辑：输入框保留手输/粘贴自由度，右侧按钮开选择浮层——搜标题/来源、
 *  点选即插入归一化 id、已选再点移除；浮层内自带字数与来源，选块不再抄 blk_id。 */
export function MaterialCellEditor({
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
    const cur = value === EMPTY_CELL ? '' : value // 占位符不参与拼接，免得存成「— blk_…」
    const next = ids.includes(id) ? cur.replace(id, ' ') : `${cur.trim()} ${id}`
    onChange(next.replace(/\s{2,}/g, ' ').trim() || EMPTY_CELL)
  }

  const ql = q.trim().toLowerCase()
  const shown = [...blockMap.values()].filter(
    (b) => !ql || (b.title || b.id).toLowerCase().includes(ql) || (b.file_name ?? '').toLowerCase().includes(ql),
  )
  const LIMIT = 50

  return (
    <div>
      <div ref={wrapRef} className="flex items-start gap-1">
        <CellInput value={value} onChange={onChange} placeholder="未指定素材——点右侧从素材库选块，没有就填【缺】" className="flex-1" />
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
 *  点选插入归一化编号、再点移除；无目录产物时按钮禁用（仍可手输）。 */
export function RefCellEditor({
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
    const cur = value === EMPTY_CELL ? '' : value // 占位符不参与拼接，免得存成「— REQ-01」
    const next = ids.includes(id) ? cur.replace(id, ' ') : `${cur.trim()} ${id}`
    onChange(next.replace(/\s{2,}/g, ' ').trim() || EMPTY_CELL)
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
        <CellInput value={value} onChange={onChange} placeholder="未指定依据——点右侧从登记表选，或手输编号（如 REQ-01）" className="flex-1" />
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

export { CellText, RowDelete }
