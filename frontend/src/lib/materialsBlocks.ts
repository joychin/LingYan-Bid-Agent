import type { MtBlock, MtOutlineNode } from '@/api/client'

/** 区间集合完全相同（排序后逐位比较；块区间服务端已夹紧排序去重）。 */
export function sameRanges(a: [number, number][], b: number[][] | undefined): boolean {
  if (!b || a.length !== b.length) return false
  const sa = a.toSorted((x, y) => x[0] - y[0])
  const sb = b.toSorted((x, y) => x[0] - y[0])
  return sa.every((r, i) => r[0] === sb[i][0] && r[1] === sb[i][1])
}

function anyOverlap(a: [number, number][], b: number[][] | undefined): boolean {
  if (!b) return false
  return a.some(([s1, e1]) => b.some(([s2, e2]) => s1 <= e2 && s2 <= e1))
}

/** 与勾选区间冲突的已有块（同文件块由调用方过滤）：
 *  exact=区间集合完全相同（多半是重复建块）；partial=有交集但不完全相同。 */
export function overlappingBlocks(
  ranges: [number, number][],
  blocks: MtBlock[],
): { exact: MtBlock[]; partial: MtBlock[] } {
  const exact: MtBlock[] = []
  const partial: MtBlock[] = []
  for (const b of blocks) {
    if (sameRanges(ranges, b.ranges)) exact.push(b)
    else if (anyOverlap(ranges, b.ranges)) partial.push(b)
  }
  return { exact, partial }
}

/** 树过滤（保祖先链；命中节点自身保留全部子树）：返回裁剪树与命中数，q 空原样返回。 */
export function filterOutline(nodes: MtOutlineNode[], q: string): { nodes: MtOutlineNode[]; hits: number } {
  const needle = q.trim().toLowerCase()
  if (!needle) return { nodes, hits: 0 }
  let hits = 0
  const walk = (list: MtOutlineNode[]): MtOutlineNode[] => {
    const out: MtOutlineNode[] = []
    for (const n of list) {
      const self = (n['标题'] ?? '').toLowerCase().includes(needle)
      if (self) hits++
      const child = walk(n.children ?? [])
      if (self || child.length > 0) out.push(self ? n : { ...n, children: child })
    }
    return out
  }
  return { nodes: walk(nodes), hits }
}

/** 节点是否已建块：节点区间完全落入某块的任一区间（勾父建块后，子节点也标）。 */
export function nodeInBlock(
  node: Pick<MtOutlineNode, 'start_line' | 'end_line'>,
  blocks: MtBlock[],
): boolean {
  const s = node.start_line
  const e = node.end_line
  if (s == null || e == null) return false
  return blocks.some((b) =>
    (b.ranges ?? []).some(([bs, be]) => s >= bs && e <= be),
  )
}
