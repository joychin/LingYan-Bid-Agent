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

  // ---------- CRUD 组件级操作路径（镜像 DirectoryEditor ops 的实现——
  // 纯函数层无组件测试环境，逐行对齐组件源码防两边漂移） ----------

  /** 组件 ops 等价实现：op=undo 快照+原地改（组件侧是 clone 后 setDocs，可观察语义相同） */
  function makeEditor(docs: EditDoc[]) {
    const past: EditDoc[][] = []
    const op = (fn: (d: EditDoc[]) => void) => {
      past.push(structuredClone(docs))
      fn(docs)
    }
    const newNode = (level: number): EditNode => ({
      _id: `new${++seq}`,
      目录名称: '新章节',
      level,
      children: [],
      来源: [],
      来源位置: [],
    })
    return {
      rename: (id: string, name: string) =>
        op((d) => {
          const c = findInDocs(d, id)
          if (c) c.list[c.index].目录名称 = name
        }),
      remove: (id: string) =>
        op((d) => {
          const c = findInDocs(d, id)
          if (c) c.list.splice(c.index, 1)
        }),
      addSibling: (id: string) =>
        op((d) => {
          const c = findInDocs(d, id)
          if (c) c.list.splice(c.index + 1, 0, newNode(c.list[c.index].level))
        }),
      addChild: (id: string) =>
        op((d) => {
          const c = findInDocs(d, id)
          if (!c) return
          const node = c.list[c.index]
          node.children = node.children ?? []
          node.children.push(newNode(node.level + 1))
        }),
      move: (id: string, dir: -1 | 1) =>
        op((d) => {
          const c = findInDocs(d, id)
          if (!c) return
          const j = c.index + dir
          if (j >= 0 && j < c.list.length) {
            ;[c.list[c.index], c.list[j]] = [c.list[j], c.list[c.index]]
          }
        }),
      undo: () => {
        const prev = past.pop()
        if (prev) {
          docs.length = 0
          docs.push(...structuredClone(prev))
        }
      },
    }
  }

  const names = (docs: EditDoc[], docIdx: number, list = docs[docIdx]!.directory ?? []): string[] =>
    list.map((x) => x.目录名称)

  it('remove 叶子：节点消失、兄弟与邻册不受影响', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    ed.remove(idOf(docs, 'r1b'))
    expect(names(docs, 0, docs[0].directory![0]!.children)).toEqual(['r1a'])
    expect(names(docs, 0)).toEqual(['r1', 'r2'])
    expect(names(docs, 1)).toEqual(['b1'])
  })

  it('remove 含子节点：整棵子树一起消失', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    const r1aId = idOf(docs, 'r1a')
    ed.remove(idOf(docs, 'r1'))
    expect(names(docs, 0)).toEqual(['r2'])
    // 深层子孙也一并没了
    expect(findInDocs(docs, r1aId)).toBeNull()
  })

  it('remove 根级首位/末位/跨册', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    ed.remove(idOf(docs, 'r1'))
    expect(names(docs, 0)).toEqual(['r2'])
    ed.remove(idOf(docs, 'b1'))
    expect(names(docs, 1)).toEqual([])
  })

  it('remove 后 undo 恢复整树（含被删子树与层级）', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    ed.remove(idOf(docs, 'r1'))
    ed.undo()
    expect(names(docs, 0)).toEqual(['r1', 'r2'])
    const r1 = docs[0].directory![0]!
    expect(names(docs, 0, r1.children!)).toEqual(['r1a', 'r1b'])
    expect(r1.children![0]!.children![0]!.level).toBe(3)
  })

  it('addSibling：同 level 插在目标之后', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    ed.addSibling(idOf(docs, 'r1a'))
    const r1 = docs[0].directory![0]!
    expect(names(docs, 0, r1.children!)).toEqual(['r1a', '新章节', 'r1b'])
    expect(r1.children![1]!.level).toBe(2)
  })

  it('addChild：level+1、挂为目标末子节点', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    ed.addChild(idOf(docs, 'r2'))
    const r2 = docs[0].directory![1]!
    expect(names(docs, 0, r2.children!)).toEqual(['新章节'])
    expect(r2.children![0]!.level).toBe(2)
  })

  it('rename：只改名称不动结构（结构确认条不触发）', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    const base = structureSignature(docs)
    ed.rename(idOf(docs, 'r1a'), '改名字')
    expect(structureSignature(docs)).toBe(base)
  })

  it('move 上移/下移：边界（首上移/末下移）为 no-op', () => {
    const docs = sample()
    const ed = makeEditor(docs)
    ed.move(idOf(docs, 'r1'), -1)
    expect(names(docs, 0)).toEqual(['r1', 'r2'])
    ed.move(idOf(docs, 'r2'), 1)
    expect(names(docs, 0)).toEqual(['r1', 'r2'])
    ed.move(idOf(docs, 'r2'), -1)
    expect(names(docs, 0)).toEqual(['r2', 'r1'])
  })

  it('结构确认闸判定：新增同级/子级、移动、删除都变签名，改名不变', () => {
    const base = structureSignature(sample())

    const added = sample()
    makeEditor(added).addSibling(idOf(added, 'r1'))
    expect(structureSignature(added)).not.toBe(base)

    const childed = sample()
    makeEditor(childed).addChild(idOf(childed, 'r2'))
    expect(structureSignature(childed)).not.toBe(base)

    const moved = sample()
    makeEditor(moved).move(idOf(moved, 'r2'), -1)
    expect(structureSignature(moved)).not.toBe(base)

    const removed = sample()
    makeEditor(removed).remove(idOf(removed, 'r1b'))
    expect(structureSignature(removed)).not.toBe(base)
  })
})
