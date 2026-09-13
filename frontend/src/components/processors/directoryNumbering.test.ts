/**
 * 章节编号预览纯函数用例：三种格式序列 / 深层计数重置 / 中文数字进位 /
 * 封面不占号（仅树首一级叶子豁免）/ none 全空 / numberTree 纯度（不改入参）。
 * 期望值口径 = sidecar docx_ops._HeadingNumberer（合册真值实现）。
 */

import { describe, expect, it } from 'vitest'
import { createNumberer, numberTree, type NumberedNode } from './directoryNumbering'
import type { EditNode } from './directoryTree'

function n(目录名称: string, level: number, children: EditNode[] = []): EditNode {
  return { _id: 目录名称, 目录名称, level, children, 来源: [], 来源位置: [] }
}

/** 装饰树 → (名称, 前缀) 扁平序列（先序）。 */
function flat(list: NumberedNode[]): Array<[string, string]> {
  const out: Array<[string, string]> = []
  const walk = (nodes: NumberedNode[]) => {
    for (const d of nodes) {
      out.push([d.node.目录名称, d.prefix])
      if (d.children.length) walk(d.children)
    }
  }
  walk(list)
  return out
}

describe('createNumberer', () => {
  it('chapter：第X章　+ 1.1，深层计数随新章重置', () => {
    const num = createNumberer('chapter')
    expect(num.prefix(1)).toBe('第一章\u3000')
    expect(num.prefix(2)).toBe('1.1 ')
    expect(num.prefix(2)).toBe('1.2 ')
    expect(num.prefix(1)).toBe('第二章\u3000')
    expect(num.prefix(2)).toBe('2.1 ')
    expect(num.prefix(3)).toBe('2.1.1 ')
  })

  it('decimal：1 / 1.1', () => {
    const num = createNumberer('decimal')
    expect(num.prefix(1)).toBe('1 ')
    expect(num.prefix(2)).toBe('1.1 ')
    expect(num.prefix(2)).toBe('1.2 ')
    expect(num.prefix(1)).toBe('2 ')
  })

  it('gov：一、（一）1.（三级无尾随空格，对齐合册实现）', () => {
    const num = createNumberer('gov')
    expect(num.prefix(1)).toBe('一、')
    expect(num.prefix(2)).toBe('（一）')
    expect(num.prefix(3)).toBe('1.')
    expect(num.prefix(2)).toBe('（二）')
    expect(num.prefix(1)).toBe('二、')
  })

  it('none：全空且不消费序号', () => {
    const num = createNumberer('none')
    expect(num.prefix(1)).toBe('')
    expect(num.prefix(2)).toBe('')
    expect(num.prefix(1)).toBe('')
  })

  it('中文数字进位：十一（1–99 规则）', () => {
    const num = createNumberer('chapter')
    for (let i = 0; i < 10; i++) num.prefix(1)
    expect(num.prefix(1)).toBe('第十一章\u3000')
  })

  it('未知格式回落 chapter，越界深度返回空', () => {
    // @ts-expect-error 防御路径：运行时可能收到非法值
    expect(createNumberer('bogus').prefix(1)).toBe('第一章\u3000')
    expect(createNumberer('chapter').prefix(0)).toBe('')
    expect(createNumberer('chapter').prefix(10)).toBe('')
  })
})

describe('numberTree', () => {
  it('封面不占号，后继从第一章起；纯度：不改入参', () => {
    const tree = [n('封面', 1), n('报价说明', 1, [n('报价口径', 2)])]
    const raw = JSON.stringify(tree)
    expect(flat(numberTree(tree, 'chapter'))).toEqual([
      ['封面', ''],
      ['报价说明', '第一章\u3000'],
      ['报价口径', '1.1 '],
    ])
    expect(JSON.stringify(tree)).toBe(raw)
  })

  it('封面仅认树首一级叶子：带子节点或非首位都正常编号', () => {
    const tree = [n('封面', 1, [n('内页', 2)]), n('封面', 1)]
    const out = numberTree(tree, 'chapter')
    expect(out[0]!.prefix).toBe('第一章\u3000')
    expect(out[0]!.children[0]!.prefix).toBe('1.1 ')
    expect(out[1]!.prefix).toBe('第二章\u3000')
  })

  it('none 全空', () => {
    expect(flat(numberTree([n('A', 1, [n('B', 2)])], 'none')).every(([, p]) => p === '')).toBe(true)
  })
})
