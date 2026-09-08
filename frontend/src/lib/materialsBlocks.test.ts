import { describe, expect, it } from 'vitest'
import type { MtBlock, MtOutlineNode } from '@/api/client'
import { filterOutline, nodeInBlock, overlappingBlocks, sameRanges } from './materialsBlocks'

function block(id: string, ranges: number[][], title = id): MtBlock {
  return { id, file_id: 'f1', title, note: '', ranges, chars: 0, created_at: '2026-09-07T00:00:00' }
}

function node(title: string, start?: number, end?: number, children: MtOutlineNode[] = []): MtOutlineNode {
  return { 标题: title, start_line: start ?? null, end_line: end ?? null, children }
}

describe('sameRanges', () => {
  it('排序后逐位相同才算一致', () => {
    expect(sameRanges([[1, 5]], [[1, 5]])).toBe(true)
    expect(sameRanges([[10, 20], [1, 5]], [[1, 5], [10, 20]])).toBe(true)
    expect(sameRanges([[1, 5]], [[1, 6]])).toBe(false)
    expect(sameRanges([[1, 5]], [[1, 5], [7, 9]])).toBe(false)
    expect(sameRanges([[1, 5]], undefined)).toBe(false)
  })
})

describe('overlappingBlocks', () => {
  it('区间集合完全相同 → exact；相交但不相同 → partial；无交集 → 都不进', () => {
    const blocks = [
      block('a', [[26, 650]]),
      block('b', [[100, 200], [300, 400]]),
      block('c', [[900, 950]]),
    ]
    const r = overlappingBlocks([[26, 650]], blocks)
    expect(r.exact.map((b) => b.id)).toEqual(['a'])
    expect(r.partial.map((b) => b.id)).toEqual(['b'])
    const r2 = overlappingBlocks([[150, 350]], blocks)
    expect(r2.exact).toEqual([])
    expect(r2.partial.map((b) => b.id)).toEqual(['a', 'b'])
    const r3 = overlappingBlocks([[1000, 1100]], blocks)
    expect(r3.exact).toEqual([])
    expect(r3.partial).toEqual([])
  })
})

describe('filterOutline', () => {
  const tree = [
    node('表单设计', 1, 10, [node('设计模式', 2, 5), node('表单组件', 6, 9)]),
    node('流程设计', 11, 30, [node('流程建模', 12, 20)]),
  ]
  it('命中保留自身全部子树，未命中但有命中后代保留裁剪子树', () => {
    const { nodes, hits } = filterOutline(tree, '流程')
    expect(hits).toBe(2)
    expect(nodes).toHaveLength(1)
    expect(nodes[0]['标题']).toBe('流程设计')
    expect(nodes[0].children).toHaveLength(1)
  })
  it('命中叶子会带出祖先链', () => {
    const { nodes, hits } = filterOutline(tree, '组件')
    expect(hits).toBe(1)
    expect(nodes).toHaveLength(1)
    expect(nodes[0]['标题']).toBe('表单设计')
    expect(nodes[0].children?.[0]['标题']).toBe('表单组件')
  })
  it('q 为空原样返回', () => {
    expect(filterOutline(tree, '  ').nodes).toBe(tree)
  })
})

describe('nodeInBlock', () => {
  it('节点区间完全落入块任一区间才算（勾父建块后子节点也标）', () => {
    const blocks = [block('a', [[26, 650], [700, 800]])]
    expect(nodeInBlock({ start_line: 100, end_line: 200 }, blocks)).toBe(true)
    expect(nodeInBlock({ start_line: 640, end_line: 700 }, blocks)).toBe(false)
    expect(nodeInBlock({ start_line: null, end_line: null }, blocks)).toBe(false)
  })
})
