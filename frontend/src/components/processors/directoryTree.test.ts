/**
 * 目录树编辑纯函数用例：跨层级移动三落点 / 升降级 / 后代拦截 / 层级封顶 /
 * 结构签名（结构性变更检测的判定基础）。
 */

import { describe, expect, it } from 'vitest'
import {
  demote,
  findInDocs,
  findParent,
  isDescendant,
  MAX_LEVEL,
  moveTo,
  promote,
  relevel,
  structureSignature,
  type EditDoc,
  type EditNode,
} from './directoryTree'

let seq = 0
function n(目录名称: string, level: number, children: EditNode[] = []): EditNode {
  return { _id: `n${++seq}`, 目录名称, level, children, 来源: [], 来源位置: [] }
}

/** 两册样例：
 *  A: r1 ─ r1a(2) ─ r1a1(3)   r2
 *  B: b1 ─ b1a(2) */
function sample(): EditDoc[] {
  return [
    {
      name: 'A',
      directory: [
        n('r1', 1, [n('r1a', 2, [n('r1a1', 3)]), n('r1b', 2)]),
        n('r2', 1),
      ],
    },
    { name: 'B', directory: [n('b1', 1, [n('b1a', 2)])] },
  ]
}

const idOf = (docs: EditDoc[], name: string): string => {
  const find = (list: EditNode[]): EditNode | undefined => {
    for (const x of list) {
      if (x.目录名称 === name) return x
      const r = find(x.children ?? [])
      if (r) return r
    }
    return undefined
  }
  for (const d of docs) {
    const r = find(d.directory ?? [])
    if (r) return r._id!
  }
  throw new Error(`no node ${name}`)
}

describe('directoryTree', () => {
  it('moveTo inside：跨层级成为目标子节点，整子树 level 重算', () => {
    const docs = sample()
    const ok = moveTo(docs, idOf(docs, 'r2'), idOf(docs, 'r1a'), 'inside')
    expect(ok).toBe(true)
    const r1a = findInDocs(docs, idOf(docs, 'r1a'))!.list[findInDocs(docs, idOf(docs, 'r1a'))!.index]
    expect(r1a.children!.map((c) => c.目录名称)).toEqual(['r1a1', 'r2'])
    expect(r1a.children![1].level).toBe(3)
  })

  it('moveTo below：插到目标同级之后（跨父级），level 对齐目标', () => {
    const docs = sample()
    const ok = moveTo(docs, idOf(docs, 'b1a'), idOf(docs, 'r1'), 'below')
    expect(ok).toBe(true)
    const rootA = docs[0].directory!
    expect(rootA.map((x) => x.目录名称)).toEqual(['r1', 'b1a', 'r2'])
    expect(rootA[1].level).toBe(1)
  })

  it('moveTo above：splice 后目标索引位移按 _id 重定位', () => {
    const docs = sample()
    // 同一列表内后移：r1 拖到 r1b 之后（from.index < to.index 场景）
    const ok = moveTo(docs, idOf(docs, 'r1a'), idOf(docs, 'r1b'), 'below')
    expect(ok).toBe(true)
    const r1 = docs[0].directory![0]
    expect(r1.children!.map((c) => c.目录名称)).toEqual(['r1b', 'r1a'])
    expect(r1.children![1].children![0].目录名称).toBe('r1a1')
    expect(r1.children![1].children![0].level).toBe(3)
  })

  it('moveTo 拖入自身后代被拦截', () => {
    const docs = sample()
    expect(moveTo(docs, idOf(docs, 'r1'), idOf(docs, 'r1a1'), 'inside')).toBe(false)
    expect(moveTo(docs, idOf(docs, 'r1a'), idOf(docs, 'r1a1'), 'above')).toBe(false)
  })

  it('moveTo inside 层级封顶：目标已 5 级不可再入', () => {
    const docs = [{ name: 'A', directory: [n('l1', 1)] } satisfies EditDoc]
    let cur = docs[0].directory![0]
    for (let i = 2; i <= MAX_LEVEL; i++) {
      cur.children = [n(`l${i}`, i)]
      cur = cur.children[0]
    }
    expect(moveTo(docs, idOf(docs, 'l1'), idOf(docs, `l${MAX_LEVEL}`), 'inside')).toBe(false)
  })

  it('promote/demote：升级上移一层、降级并入前同级', () => {
    const docs = sample()
    expect(promote(docs, idOf(docs, 'r1a1'))).toBe(true)
    const r1 = docs[0].directory![0]
    expect(r1.children!.map((c) => c.目录名称)).toEqual(['r1a', 'r1a1', 'r1b'])
    expect(r1.children![1].level).toBe(2)

    expect(demote(docs, idOf(docs, 'r1b'))).toBe(true)
    // r1b 并入前同级 r1a1 的子节点
    const r1a1 = r1.children!.find((c) => c.目录名称 === 'r1a1')!
    expect(r1a1.children!.map((c) => c.目录名称)).toEqual(['r1b'])
    expect(r1a1.children![0].level).toBe(3)
  })

  it('promote 根级不可 / demote 首位不可', () => {
    const docs = sample()
    expect(promote(docs, idOf(docs, 'r1'))).toBe(false)
    expect(demote(docs, idOf(docs, 'r1'))).toBe(false)
  })

  it('isDescendant / findParent', () => {
    const docs = sample()
    expect(isDescendant(docs, idOf(docs, 'r1'), idOf(docs, 'r1a1'))).toBe(true)
    expect(isDescendant(docs, idOf(docs, 'r1a1'), idOf(docs, 'r1'))).toBe(false)
    expect(isDescendant(docs, idOf(docs, 'r1'), idOf(docs, 'r1'))).toBe(false)
    expect(findParent(docs, idOf(docs, 'r1a1'))?.parent?.目录名称).toBe('r1a')
    expect(findParent(docs, idOf(docs, 'r1'))?.parent).toBeNull()
    expect(findParent(docs, idOf(docs, 'b1a'))?.docIndex).toBe(1)
  })

  it('relevel 整子树重算', () => {
    const docs = sample()
    const r1a = findInDocs(docs, idOf(docs, 'r1a'))!.list[findInDocs(docs, idOf(docs, 'r1a'))!.index]
    relevel(r1a, 5)
    expect(r1a.level).toBe(5)
    expect(r1a.children![0].level).toBe(6) // relevel 不封顶（封顶由操作入口校验）
  })

  it('structureSignature：增删/移动变化，改名不变', () => {
    const base = structureSignature(sample())

    const renamed = sample()
    findInDocs(renamed, idOf(renamed, 'r1a'))!.list[0].目录名称 = '改名了'
    expect(structureSignature(renamed)).toBe(base)

    const moved = sample()
    moveTo(moved, idOf(moved, 'r2'), idOf(moved, 'r1a'), 'inside')
    expect(structureSignature(moved)).not.toBe(base)

    const removed = sample()
    const r1 = findInDocs(removed, idOf(removed, 'r1'))!
    r1.list.splice(r1.index, 1)
    expect(structureSignature(removed)).not.toBe(base)
  })
})
