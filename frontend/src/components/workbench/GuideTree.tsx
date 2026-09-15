/**
 * 写作指引左栏：章节树导航（2026-09-13 两栏重构）。
 *
 * 树按**目录真实层级**渲染，指引没给行的节点以「未分配」态挂在原位——
 * 漏节在查看态一眼可见（旧表格里这类问题完全看不见）。
 * 顶部搜索 + 筛选胶囊与树共用同一套裁剪（pruneTree 保留祖先链）。
 * 树底部固定「不在目录」组：指引有行、目录里找不到（目录改版后未对账）。
 */

import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Search, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DirLeaf } from '@/lib/workbenchTable'
import { countUnassigned, pruneTree, type GuideTreeNode, type GuideTreeFilter } from '@/lib/guideTree'
import { FilterPills, LeafPicker } from './guideBits'

/** 叶子状态（圆点配色）。 */
export type GuideNodeStatus = 'written' | 'todo' | 'issue' | 'unassigned'

const DOT: Record<GuideNodeStatus, string> = {
  written: 'bg-success',
  todo: 'bg-ink-3/70',
  issue: 'bg-warning',
  unassigned: 'border border-ink-3 bg-transparent',
}

/** 树行样式（容器行与叶子行共用；选中=品牌色浅底）。 */
function rowClass(active: boolean) {
  return cn(
    'flex w-full items-center gap-1 rounded-md py-1 pr-1.5 text-left text-xs',
    active ? 'bg-accent-soft font-medium text-primary' : 'text-ink-2 hover:bg-muted',
  )
}

export function GuideTree({
  nodes,
  selectedKey,
  onSelect,
  filter,
  onFilter,
  counts,
  statusOf,
  matches,
  offTreeRows,
  editing,
  leaves,
  usedKeys,
  multi,
  onPickLeaf,
}: {
  nodes: GuideTreeNode[]
  selectedKey: string | null
  onSelect: (key: string) => void
  filter: GuideTreeFilter
  onFilter: (f: GuideTreeFilter) => void
  counts: Record<GuideTreeFilter, number>
  /** 叶子状态（圆点配色）；容器节点不调用 */
  statusOf: (n: GuideTreeNode) => GuideNodeStatus
  /** 节点是否命中当前筛选 + 搜索（容器恒 true，靠 pruneTree 的祖先规则保留） */
  matches: (n: GuideTreeNode) => boolean
  /** 指引有行但不在目录叶子中的行（「不在目录」组） */
  offTreeRows: { label: string; rowIndex: number }[]
  editing: boolean
  leaves: DirLeaf[]
  usedKeys: Set<string>
  multi: boolean
  onPickLeaf: (l: DirLeaf) => void
}) {
  const [q, setQ] = useState('')
  const [folded, setFolded] = useState<Set<string>>(new Set())

  const ql = q.trim().toLowerCase()
  const shown = useMemo(
    () => pruneTree(nodes, (n) => matches(n) && (!ql || n.label.toLowerCase().includes(ql))),
    [nodes, matches, ql],
  )

  const unassigned = useMemo(() => countUnassigned(nodes), [nodes])
  const hasFilters = counts.missing + unassigned + counts.stale + counts.offtree > 0
  const showOffTree = offTreeRows.length > 0 && (filter === 'all' || filter === 'offtree')

  const toggle = (key: string) =>
    setFolded((s) => {
      const next = new Set(s)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const renderNode = (n: GuideTreeNode, depth: number): React.ReactNode => {
    const isContainer = n.children.length > 0
    const active = selectedKey === n.key
    const pad = { paddingLeft: 6 + depth * 12 }
    if (isContainer) {
      const f = folded.has(n.key)
      return (
        <div key={n.key}>
          <button type="button" onClick={() => toggle(n.key)} className={cn(rowClass(false), 'font-medium text-ink')} style={pad}>
            {f ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-3" /> : <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-3" />}
            <span className="min-w-0 flex-1 truncate" title={n.label}>
              {n.label}
            </span>
          </button>
          {!f && n.children.map((c) => renderNode(c, depth + 1))}
        </div>
      )
    }
    const st = statusOf(n)
    return (
      <button key={n.key} type="button" onClick={() => onSelect(n.key)} className={rowClass(active)} style={pad} title={n.label}>
        <span className="w-3.5 shrink-0" />
        <span className={cn('min-w-0 flex-1 truncate', st === 'unassigned' && 'text-ink-3')}>{n.label}</span>
        {st === 'unassigned' && <span className="shrink-0 text-[11px] text-ink-3">未分配</span>}
        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT[st])} />
      </button>
    )
  }

  return (
    // 宽度按比例夹取而非定死：面板体（宽态下 = 面板宽 − 260px 文件列表列）实测仅
    // 500~750px，定死 272px 会把右栏挤到 236px 不可用。38% 保证窄面板下右栏仍有
    // 内容宽度，最大 300px 防宽面板下树占得过多。
    <aside className="flex h-full min-h-0 w-[38%] min-w-[196px] max-w-[300px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex shrink-0 flex-col gap-2 border-b border-line px-2.5 py-2">
        <div className="flex items-center gap-1.5 rounded-md border border-line bg-canvas px-2 py-1">
          <Search className="h-3.5 w-3.5 shrink-0 text-ink-3" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索章节"
            className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-ink-3"
          />
        </div>
        <FilterPills value={filter} counts={counts} onChange={onFilter} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
        {shown.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-ink-3">
            {ql || hasFilters ? '没有命中的章节——换个筛选或清空搜索。' : '目录还没有节点。'}
          </p>
        ) : (
          shown.map((n) => renderNode(n, 0))
        )}

        {showOffTree && (
          <div className="mt-2 border-t border-line pt-1.5">
            <p className="flex items-center gap-1 px-1.5 py-1 text-[11px] font-medium text-warning">
              <TriangleAlert className="h-3 w-3 shrink-0" />
              不在目录 {offTreeRows.length} 节
            </p>
            {offTreeRows.map((r) => {
              const active = selectedKey === r.label
              return (
                <button
                  key={r.rowIndex}
                  type="button"
                  onClick={() => onSelect(r.label)}
                  className={rowClass(active)}
                  style={{ paddingLeft: 18 }}
                  title={`「${r.label}」不在目录叶子中——节名须与目录逐字一致`}
                >
                  <span className="min-w-0 flex-1 truncate">{r.label}</span>
                  <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT.issue)} />
                </button>
              )
            })}
          </div>
        )}
      </div>

      {editing && leaves.length > 0 && (
        <div className="shrink-0 border-t border-line p-2.5">
          <LeafPicker leaves={leaves} usedKeys={usedKeys} multi={multi} onPick={onPickLeaf} />
        </div>
      )}
    </aside>
  )
}
