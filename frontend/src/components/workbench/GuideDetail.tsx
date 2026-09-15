/**
 * 写作指引右栏：选中节点的详情（2026-09-13 两栏重构）。
 *
 * 查看态=「本节作业单」——内容合并了旧表格的行内单元格与行展开面板：
 * 本节写什么（目录节点概述/归位理由/交付形态）、怎么写（模式）、依据（定性摘要 +
 * 逐条登记原文与出处切片）、素材（块 chip + 首段预览）。
 * 编辑态=同位置的表单——模式 toggle、依据/素材带选择浮层、缺口备注、删行。
 *
 * 未分配节点（目录有、指引无行）：空态给加行入口（写操作仍由「编辑」按钮把关）。
 */

import { AlertTriangle, ChevronDown, ExternalLink, FileText, Wrench } from 'lucide-react'
import type { MtBlock } from '@/api/client'
import { cn } from '@/lib/utils'
import { SourceEntryCard, type SourceEntry } from '@/components/processors/SourceTraceDialog'
import { badgeStyle } from '@/components/processors/DirectoryProcessor'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { scoreValueBadge, type RowBasis, type ScoreRow } from '@/lib/guideBasis'
import {
  blockPreviewText,
  parseBlockRefs,
  parseGuideNote,
  parseModeTokens,
  parseRefIds,
  type DirLeaf,
} from '@/lib/workbenchTable'
import type { GuideTreeNode } from '@/lib/guideTree'
import type { GuideNodeStatus } from './GuideTree'
import {
  BlockChip,
  MaterialCellEditor,
  ModeBadges,
  ModeToggles,
  RefChip,
  RefCellEditor,
  RowDelete,
} from './guideBits'
import { CellInput } from './tableBits'

const STATUS_LABEL: Record<GuideNodeStatus, string> = {
  written: '已写',
  todo: '待写',
  issue: '有问题',
  unassigned: '未分配',
}
const STATUS_CLASS: Record<GuideNodeStatus, string> = {
  written: 'bg-success-soft text-success',
  todo: 'bg-muted text-ink-3',
  issue: 'bg-warning/15 text-warning',
  unassigned: 'bg-warning/15 text-warning',
}

/** 详情分块小标题。 */
function Sec({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-semibold text-ink-2">{title}</h3>
      {children}
    </section>
  )
}

/** 备注列条目组（缺口/待澄清/知识库命中）：空则不渲染——小标题也不留空壳。
 *  hint=可选的额外说明行（缺口项用代词回指时的指代去处）。 */
function NoteList({
  title,
  items,
  tone,
  hint,
}: {
  title: string
  items: string[]
  tone: 'warning' | 'neutral'
  hint?: string
}) {
  if (!items.length) return null
  const cls =
    tone === 'warning'
      ? 'bg-warning/15 text-warning'
      : 'bg-muted/40 text-ink-2'
  return (
    <div className="flex flex-col gap-1">
      <p className={cn('self-start rounded-full px-1.5 py-px text-[11px] font-medium', cls)}>{title}</p>
      <ul className="flex flex-col gap-1">
        {items.map((t, k) => (
          <li
            key={k}
            className="rounded-lg bg-muted/40 px-3 py-2 text-xs leading-relaxed text-ink-2"
          >
            {t}
          </li>
        ))}
      </ul>
      {hint && <p className="text-[11px] leading-relaxed text-ink-3">{hint}</p>}
    </div>
  )
}

export function GuideDetail({
  node,
  row,
  rowIndex,
  writtenPath,
  basis,
  registry,
  scores,
  blockMap,
  blockPreviews,
  blockUsage,
  taskId,
  editing,
  status,
  onTrace,
  onOpenBlock,
  onOpenWorkbench,
  onOpenLibrary,
  onChangeCell,
  onAddRow,
  onDeleteRow,
}: {
  node: GuideTreeNode | null
  row: string[] | null
  rowIndex: number
  writtenPath: string | undefined
  basis: RowBasis | null
  registry: Record<string, SourceEntry> | null
  scores: Map<string, ScoreRow>
  blockMap: Map<string, MtBlock>
  blockPreviews: Map<string, { preview: string; chars: number }>
  blockUsage: Map<string, number>
  taskId: string | null
  editing: boolean
  status: GuideNodeStatus
  onTrace: (id: string) => void
  onOpenBlock: (b: MtBlock) => void
  onOpenWorkbench: (path: string) => void
  onOpenLibrary?: () => void
  onChangeCell: (col: number, v: string) => void
  onAddRow: () => void
  onDeleteRow: () => void
}) {
  if (!node) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-muted-foreground">
        从左侧选择一个章节，查看它的写作要求。
      </div>
    )
  }

  const unassigned = rowIndex < 0
  const leaf: DirLeaf | null = node.leaf
  const refs = parseRefIds(row?.[2] ?? '')
  const mat = parseBlockRefs(row?.[3] ?? '')
  const fig = (row?.[4] ?? '').trim()
  const figItems = fig && fig !== '—'
    ? fig.split(/[、;；,，]/).map((x) => x.trim()).filter(Boolean)
    : []
  const note = (row?.[5] ?? '').trim()
  const noteParts = parseGuideNote(note)
  const matBlocks = mat.blockIds.flatMap((id) => {
    const pv = blockPreviews.get(id)
    return pv ? [{ id, preview: pv.preview, chars: pv.chars }] : []
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="flex flex-col gap-5 p-5">
        {/* 头部：节名 + 状态 + 打开正文 */}
        <div className="flex flex-wrap items-start gap-2">
          <h2 className="min-w-0 flex-1 text-base font-semibold leading-snug">{node.label}</h2>
          <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-xs font-medium', STATUS_CLASS[status])}>
            {STATUS_LABEL[status]}
          </span>
          {writtenPath && (
            <button
              type="button"
              onClick={() => onOpenWorkbench(writtenPath)}
              title="打开该节正文文件"
              className="flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-xs text-primary hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              打开正文
            </button>
          )}
        </div>

        {unassigned && !editing ? (
          <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed border-line px-4 py-5">
            <p className="flex items-center gap-1.5 text-sm font-medium text-warning">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              本节还没有指引行
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              目录里有这个章节，但写作指引没有给它分配行——AI 不会写它。点右上角「编辑」后可从目录补上。
            </p>
          </div>
        ) : (
          <>
            {/* 本节写什么（目录节点元数据；无目录产物的旧任务没有这块） */}
            {leaf && (leaf.overview || leaf.reason || leaf.delivery) && (
              <Sec title="本节写什么">
                <div className="flex flex-col gap-1 rounded-lg bg-muted/40 px-3 py-2.5 text-sm leading-relaxed text-ink-2">
                  {leaf.overview && <p>{leaf.overview}</p>}
                  {leaf.reason && (
                    <p className="text-xs">
                      <span className="mr-1 text-ink-3">为什么有这章</span>
                      {leaf.reason}
                    </p>
                  )}
                  {leaf.delivery && (
                    <p className="text-xs">
                      <span className="mr-1 text-ink-3">交付形态</span>
                      {leaf.delivery}
                    </p>
                  )}
                </div>
              </Sec>
            )}

            {/* 怎么写（模式） */}
            <Sec title="怎么写">
              {editing && row ? (
                <ModeToggles value={row[1] ?? ''} onChange={(v) => onChangeCell(1, v)} />
              ) : (
                <ModeBadges tokens={parseModeTokens(row?.[1] ?? '')} />
              )}
            </Sec>

            {/* 依据：定性摘要 + 逐条登记原文与出处切片 */}
            <Sec title="依据">
              {basis?.stance && (
                <p className="text-xs leading-relaxed text-ink-3">
                  <span className="mr-1 rounded-full bg-warning/15 px-1.5 py-px font-medium text-warning">{basis.stance}</span>
                  {basis.summaryLine}
                </p>
              )}
              {editing && row ? (
                <div className="flex flex-col gap-2">
                  <RefCellEditor
                    value={row[2] ?? ''}
                    onChange={(v) => onChangeCell(2, v)}
                    registry={registry}
                    scores={scores}
                  />
                  {refs.ids.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1">
                      {refs.ids.map((id) => (
                        <RefChip
                          key={id}
                          id={id}
                          badge={basis?.badges.get(id)}
                          traceable={registry !== null}
                          known={registry ? id in registry : false}
                          onClick={() => onTrace(id)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ) : refs.ids.length === 0 ? (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  本节没有关联登记编号——按模式与招标格式件写作（模板填充/附件类，或补依据后重新生成指引）。
                </p>
              ) : (
                <div className="flex flex-col gap-4">
                  {refs.ids.map((id) => {
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
                              分值 {scoreValueBadge(score.value) ?? score.value}
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
            </Sec>

            {/* 素材 */}
            <Sec title="素材">
              {editing && row ? (
                <MaterialCellEditor
                  value={row[3] ?? ''}
                  onChange={(v) => onChangeCell(3, v)}
                  blockMap={blockMap}
                  usage={blockUsage}
                  onOpenBlock={onOpenBlock}
                  onOpenLibrary={onOpenLibrary}
                />
              ) : mat.blockIds.length === 0 && !mat.missing ? (
                <p className="text-xs text-muted-foreground">本节没有指定素材块——按模式写作或先补素材。</p>
              ) : (
                <div className="flex flex-col gap-2.5">
                  <div className="flex flex-wrap items-center gap-1">
                    {mat.blockIds.map((id) => (
                      <BlockChip
                        key={id}
                        id={id}
                        block={blockMap.get(id)}
                        usage={blockUsage.get(id) ?? 1}
                        onOpen={() => {
                          const b = blockMap.get(id)
                          if (b) onOpenBlock(b)
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
                    {/* 「—」= 空值占位，不再显示（与编辑态预览同口径） */}
                    {mat.rest && mat.rest !== '—' && (
                      <span className="break-words text-xs text-ink-3">{mat.rest}</span>
                    )}
                  </div>
                  {matBlocks.map(({ id, preview, chars }) => (
                    <div key={id} className="rounded-lg bg-muted/40 px-3 py-2 text-xs leading-relaxed text-ink-2">
                      <p className="line-clamp-4" title={preview}>
                        {preview || blockPreviewText(undefined, 0) || '（块内容为空）'}
                      </p>
                      <p className="mt-1 text-ink-3">共 {chars.toLocaleString()} 字</p>
                    </div>
                  ))}
                </div>
              )}
            </Sec>

            {/* 图示（2026-09-14 表格通道批）：本节计划产出的表格/图示清单——
                类型:主题；「计划先行」的用户可见面（validate 节级对账看这列）。 */}
            {editing && row ? (
              <Sec title="图示">
                <CellInput
                  value={row[4] ?? ''}
                  onChange={(v) => onChangeCell(4, v)}
                  placeholder="图示（类型:主题，如 甘特:实施进度计划、表:岗位配置；无则 —）"
                />
              </Sec>
            ) : (
              figItems.length > 0 && (
                <Sec title="图示">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {figItems.map((item, i) => {
                      const m = /^(表|分层|辐射|甘特)\s*[:：]\s*(.+)$/.exec(item)
                      return m ? (
                        <span key={i} className="inline-flex items-center gap-1 rounded-full border border-line bg-accent-soft px-2 py-0.5 text-xs">
                          <span className="font-medium text-primary">{m[1]}</span>
                          <span className="text-ink-2">{m[2]}</span>
                        </span>
                      ) : (
                        <span key={i} className="text-xs text-ink-3">{item}</span>
                      )
                    })}
                  </div>
                </Sec>
              )
            )}

            {/* 缺口/备注（编辑态可改；查看态有内容才显示）。
                读者分离（2026-09-13 A 批）：该列同时是给写手的执行指令与给用户的
                缺料点名，「需要你提供」摘出来摆最前，工具名/行号等执行细节折叠。 */}
            {editing && row ? (
              <Sec title="缺口/备注">
                <CellInput
                  value={row[5] ?? ''}
                  onChange={(v) => onChangeCell(5, v)}
                  placeholder="缺口/备注（【缺：具体字段名】；不写工具名与行号）"
                />
              </Sec>
            ) : (
              note &&
              note !== '—' && (
                <Sec title="备注">
                  <div className="flex flex-col gap-2">
                    <NoteList
                      title="需要你提供"
                      items={noteParts.gaps}
                      tone="warning"
                      hint={
                        noteParts.anaphora
                          ? '条目里的「上述…」指代下方「AI 执行说明」中列出的字段'
                          : undefined
                      }
                    />
                    <NoteList
                      title="需要你确认"
                      items={noteParts.clarifies}
                      tone="warning"
                    />
                    <NoteList
                      title="已从你的资料中找到"
                      items={noteParts.knowledge}
                      tone="neutral"
                    />
                    {/* 执行说明：默认收起（这是给 AI 的操作细节，不是用户待办）；
                        但缺口项用代词回指时默认展开——那是用户看懂缺口的唯一线索。
                        key=节点：切换章节时强制重挂，否则 React 复用同位置实例、
                        沿用上一节的展开态（defaultOpen 只在首次挂载生效）。 */}
                    {noteParts.rest && (
                      <Collapsible
                        key={node.key}
                        className="group"
                        defaultOpen={noteParts.anaphora}
                      >
                        <CollapsibleTrigger className="flex items-center gap-1.5 text-xs text-ink-3 transition-colors hover:text-ink-2">
                          <Wrench className="h-3.5 w-3.5 shrink-0" aria-hidden />
                          <span>AI 执行说明</span>
                          <ChevronDown className="h-3.5 w-3.5 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
                        </CollapsibleTrigger>
                        <CollapsibleContent className="overflow-hidden">
                          <p className="pt-1.5 text-xs leading-relaxed text-ink-3">{noteParts.rest}</p>
                        </CollapsibleContent>
                      </Collapsible>
                    )}
                  </div>
                </Sec>
              )
            )}

            {editing && row && (
              <div className="flex items-center gap-2 border-t border-line pt-3">
                <RowDelete
                  hint="删行后该节回到「指引缺行」状态（AI 按权重 1 兜底派发或提示缺行）"
                  onConfirm={onDeleteRow}
                />
                <span className="text-xs text-ink-3">删行后本节点会退回「未分配」</span>
              </div>
            )}
          </>
        )}

        {editing && unassigned && (
          <button
            type="button"
            onClick={onAddRow}
            className="flex w-fit items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-xs text-muted-foreground hover:border-primary hover:text-foreground"
          >
            <FileText className="h-3.5 w-3.5" />
            + 为「{node.label}」添加指引行
          </button>
        )}
      </div>
    </div>
  )
}
