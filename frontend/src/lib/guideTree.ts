/**
 * 写作指引「左树右详情」的导航树派生（纯函数，2026-09-13 两栏重构）。
 *
 * 节点范围取**目录真实层级**而非指引已有行——目录里有节点、指引没给它行时，
 * 该节点以「未分配」（rowIndex=-1）挂在原位上，漏节因此可见（旧表格查看态
 * 完全看不见这类问题，只有编辑态展开「+ 从目录添加节行」时才知道漏了哪些）。
 *
 * 选择键 = 叶子 leafKey（即指引「节」列的值），不是行索引——删行后节点仍在
 * 树上、自动退回未分配态，加行后原地变回表单。
 *
 * 无目录产物时回落「平坦行列表」（leaf=null、rowIndex=行序），保住既有降级路径。
 */

import type { EditDoc, EditNode } from '@/components/processors/directoryTree'
import { leafKey, type DirLeaf, type GuideFilterKey } from './workbenchTable'

/** 左栏筛选：既有行标记 + 新增「未分配」（目录有节点、指引无行）。 */
export type GuideTreeFilter = GuideFilterKey | 'unassigned'

export interface GuideTreeNode {
  /** 叶子=leafKey；容器=`#<册>/<路径>`；平坦回落行=`#row-<i>`。全树唯一。 */
  key: string
  label: string
  /** 目录叶子元数据；容器与无目录回落行为 null。 */
  leaf: DirLeaf | null
  /** 指引行索引；-1 = 目录有此节点但指引未给行。 */
  rowIndex: number
  children: GuideTreeNode[]
}

/** 行索引 → 指引行键（「节」列；空白行跳过）。 */function rowIndexByKey(rows: string[][]): Map<string, number> {
  const m = new Map<string, number>()
  rows.forEach((r, i) => {
    const key = (r[0] ?? '').trim()
    if (key && !m.has(key)) m.set(key, i)
  })
  return m
}

/** 目录真实层级 + 指引行 → 导航树；多册时册名为顶层。 */
export function guideTree(docs: EditDoc[] | undefined, rows: string[][], multi: boolean): GuideTreeNode[] {
  const byKey = rowIndexByKey(rows)
  const usable = (docs ?? []).filter((d) => (d.directory ?? []).length > 0)
  if (usable.length === 0) {
    return rows.map((r, i) => {
      const label = (r[0] ?? '').trim()
      return { key: label || `#row-${i}`, label: label || `（空行 ${i + 1}）`, leaf: null, rowIndex: i, children: [] }
    })
  }

  const build = (vol: string, list: EditNode[] | undefined, prefix: string): GuideTreeNode[] => {
    const out: GuideTreeNode[] = []
    for (const n of list ?? []) {
      const title = (n.目录名称 ?? '').trim()
      const path = prefix ? `${prefix}/${title}` : title
      if (n.children?.length) {
        const children = build(vol, n.children, path)
        // 无名容器：不下沉节点，直接摊平子级（不产生无标签的中间行）
        if (!title) out.push(...children)
        else out.push({ key: `#${vol}/${path}`, label: title, leaf: null, rowIndex: -1, children })
        continue
      }
      if (!title) continue
      const key = leafKey(vol, title, multi)
      out.push({
        key,
        label: title,
        leaf: {
          vol,
          title,
          delivery: (n.交付形态 ?? '').trim(),
          overview: (n.节点概述 ?? '').trim(),
          reason: (n.归位理由 ?? '').trim(),
        },
        rowIndex: byKey.get(key) ?? -1,
        children: [],
      })
    }
    return out
  }

  const out: GuideTreeNode[] = []
  for (const d of usable) {
    const vol = (d.name ?? '').trim() || '主册'
    const children = build(vol, d.directory, '')
    // 单册不套册名层（与 leafKey 的单册裸标题同口径）
    if (multi) out.push({ key: `#vol/${vol}`, label: vol, leaf: null, rowIndex: -1, children })
    else out.push(...children)
  }
  return out
}

/** 树上过滤：命中节点及其祖先链保留；容器无命中后代则整支剔除。 */
export function pruneTree(nodes: GuideTreeNode[], keep: (n: GuideTreeNode) => boolean): GuideTreeNode[] {
  const out: GuideTreeNode[] = []
  for (const n of nodes) {
    const children = pruneTree(n.children, keep)
    if (keep(n) || children.length > 0) out.push({ ...n, children })
  }
  return out
}

/** 未分配叶子数：目录有该节点、指引没有对应行（漏节）。 */
export function countUnassigned(nodes: GuideTreeNode[]): number {
  let n = 0
  for (const node of nodes) {
    if (node.leaf && node.rowIndex < 0) n += 1
    n += countUnassigned(node.children)
  }
  return n
}

/** 树中叶子键集合——「不在目录」的行 = 键不在本集合的行（与旧
 *  GuideRowFlags.offtree 的按名判定同口径：重复行名同属一个叶子，都算已挂）。 */
export function leafKeysOf(nodes: GuideTreeNode[]): Set<string> {
  const s = new Set<string>()
  const walk = (list: GuideTreeNode[]) => {
    for (const n of list) {
      if (n.children.length) walk(n.children)
      else if (n.leaf) s.add(n.key)
    }
  }
  walk(nodes)
  return s
}

/** 「不在目录」的行（指引有行、树里挂不上）。leafKeys 传 null=无目录产物
 *  （降级平坦行，leaf=null、leafKeysOf 恒空）——offtree 无从判定，返回空，
 *  与 guideRowFlags 的 `leafKeys !== null` 守卫同口径（否则每行都会误标）。 */
export function offTreeRowsOf(
  rows: string[][],
  leafKeys: Set<string> | null,
): { label: string; rowIndex: number }[] {
  if (leafKeys === null) return []
  return rows
    .map((r, i) => ({ label: (r[0] ?? '').trim(), rowIndex: i }))
    .filter((x) => !leafKeys.has(x.label))
}

/** 树的册序（多册时册名列表；单册为空）——详情页回填多册复合键用。 */
export function treeVolumes(nodes: GuideTreeNode[]): string[] {
  return nodes.filter((n) => n.key.startsWith('#vol/')).map((n) => n.label)
}
