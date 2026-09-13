/**
 * guideTree 纯函数测试（2026-09-13 两栏重构）：目录真实层级 + 指引行 → 导航树。
 * 锁四层——层级/册层、叶子 rowIndex 对位（含多册复合键）、未分配（漏节）识别、
 * 无目录产物的平坦回落，以及 pruneTree 的祖先链保留规则（搜索与筛选共用）。
 */

import { describe, expect, it } from 'vitest'
import type { EditDoc } from '@/components/processors/directoryTree'
import { countUnassigned, guideTree, leafKeysOf, offTreeRowsOf, pruneTree, treeVolumes } from './guideTree'

/** 单册：一章容器（两个叶子）+ 一个顶层叶子。 */
const single: EditDoc[] = [
  {
    name: '',
    directory: [
      {
        目录名称: '第三章 落实方案',
        level: 1,
        children: [
          { 目录名称: '3.1 项目理解', level: 2, children: [], 交付形态: '正文编写', 节点概述: '写需求理解' },
          { 目录名称: '3.2 总体设计', level: 2, children: [] },
        ],
      },
      { 目录名称: '投标函', level: 1, children: [], 交付形态: '模板或附件填充' },
    ],
  },
]

/** 多册：两个响应文件各带目录。 */
const multi: EditDoc[] = [
  { name: '商务部分', directory: [{ 目录名称: '投标函', level: 1, children: [] }] },
  {
    name: '技术部分',
    directory: [
      {
        目录名称: '技术方案',
        level: 1,
        children: [{ 目录名称: '总体架构', level: 2, children: [] }],
      },
    ],
  },
]

describe('guideTree（目录层级 + 指引行 → 导航树）', () => {
  it('单册不套册名层：容器/叶子层级正确，叶子 rowIndex 对位', () => {
    const rows = [
      ['3.1 项目理解', '推理撰写', 'REQ-01', 'blk_aaaaaaaaaaaa', '—'],
      ['投标函', '—', 'TPL-01', '—', '—'],
    ]
    const t = guideTree(single, rows, false)
    expect(treeVolumes(t)).toEqual([])
    expect(t.map((n) => n.label)).toEqual(['第三章 落实方案', '投标函'])
    // 容器节点：无 leaf、rowIndex = -1（不参与行绑定）
    expect(t[0].leaf).toBeNull()
    expect(t[0].rowIndex).toBe(-1)
    expect(t[0].children.map((c) => c.label)).toEqual(['3.1 项目理解', '3.2 总体设计'])
    // 叶子：键=leafKey（裸标题）、rowIndex 指向指引行、带出目录元数据
    expect(t[0].children[0].key).toBe('3.1 项目理解')
    expect(t[0].children[0].rowIndex).toBe(0)
    expect(t[0].children[0].leaf).toMatchObject({ vol: '主册', title: '3.1 项目理解', delivery: '正文编写' })
    expect(t[1].rowIndex).toBe(1)
  })

  it('多册：册名为顶层节点，叶子键为「册名/标题」复合', () => {
    const rows = [
      ['商务部分/投标函', '—', 'TPL-01', '—', '—'],
      ['技术部分/总体架构', '推理撰写', 'REQ-02', '—', '—'],
    ]
    const t = guideTree(multi, rows, true)
    expect(treeVolumes(t)).toEqual(['商务部分', '技术部分'])
    expect(t[0].children[0].key).toBe('商务部分/投标函')
    expect(t[0].children[0].rowIndex).toBe(0)
    expect(t[1].children[0].children[0].key).toBe('技术部分/总体架构')
    expect(t[1].children[0].children[0].rowIndex).toBe(1)
  })

  it('未分配：目录有节点、指引无行 → rowIndex=-1，countUnassigned 计数', () => {
    const rows = [['3.1 项目理解', '推理撰写', '—', '—', '—']]
    const t = guideTree(single, rows, false)
    expect(t[0].children[0].rowIndex).toBe(0)
    expect(t[0].children[1].rowIndex).toBe(-1) // 3.2 漏行
    expect(t[1].rowIndex).toBe(-1) // 投标函漏行
    expect(countUnassigned(t)).toBe(2)
  })

  it('行键空白行跳过、重复行取首个；leafKeysOf 按名判定「不在目录」', () => {
    const rows = [
      ['', '—', '—', '—', '—'],
      ['3.1 项目理解', '推理撰写', '—', '—', '—'],
      ['3.1 项目理解', '素材修订', '—', '—', '—'],
      ['幽灵节', '推理撰写', '—', '—', '—'],
    ]
    const t = guideTree(single, rows, false)
    expect(t[0].children[0].rowIndex).toBe(1) // 重复键取首个行
    // 按名判定：同名行同属一个叶子（旧 GuideRowFlags.offtree 口径），不误报「不在目录」
    const keys = leafKeysOf(t)
    expect(keys.has('3.1 项目理解')).toBe(true)
    expect(keys.has('幽灵节')).toBe(false)
    const notInTree = rows.map((r, i) => ({ i, key: (r[0] ?? '').trim() })).filter((x) => !keys.has(x.key))
    expect(notInTree.map((x) => x.i)).toEqual([0, 3]) // 空白行与幽灵节
  })

  it('offTreeRowsOf：leafKeys=null（无目录产物）恒空，正常 set 才筛「不在目录」', () => {
    const rows = [
      ['', '—', '—', '—', '—'],
      ['3.1 项目理解', '推理撰写', '—', '—', '—'],
      ['幽灵节', '推理撰写', '—', '—', '—'],
    ]
    // 无目录产物：降级平坦行、leaf=null、leafKeysOf 恒空——若不守卫会整组误标
    expect(offTreeRowsOf(rows, null)).toEqual([])
    // 正常目录：空白行与幽灵节不在叶子键集合内
    const keys = leafKeysOf(guideTree(single, rows, false))
    expect(offTreeRowsOf(rows, keys)).toEqual([
      { label: '', rowIndex: 0 },
      { label: '幽灵节', rowIndex: 2 },
    ])
  })

  it('无目录产物：回落平坦行列表（leaf=null，rowIndex=行序）', () => {
    const rows = [
      ['报价说明', '推理撰写', 'REQ-13', '—', '—'],
      ['报价明细表', '素材修订', 'REQ-20', '—', '—'],
    ]
    expect(guideTree(undefined, rows, false)).toEqual([
      { key: '报价说明', label: '报价说明', leaf: null, rowIndex: 0, children: [] },
      { key: '报价明细表', label: '报价明细表', leaf: null, rowIndex: 1, children: [] },
    ])
    // 空目录数组同款回落
    expect(guideTree([], rows, false)).toHaveLength(2)
    expect(guideTree([{ name: 'X', directory: [] }], rows, false)).toHaveLength(2)
    expect(countUnassigned(guideTree(undefined, rows, false))).toBe(0)
  })

  it('无名容器不下沉节点（子级摊平，不留无标签中间行）', () => {
    const docs: EditDoc[] = [
      {
        name: '',
        directory: [
          { 目录名称: '', level: 1, children: [{ 目录名称: '叶子A', level: 2, children: [] }] },
        ],
      },
    ]
    const t = guideTree(docs, [['叶子A', '推理撰写', '—', '—', '—']], false)
    expect(t).toHaveLength(1)
    expect(t[0]).toMatchObject({ key: '叶子A', label: '叶子A', rowIndex: 0 })
  })
})

describe('pruneTree（树上过滤：命中节点 + 祖先链）', () => {
  const rows = [
    ['3.1 项目理解', '推理撰写', '—', '—', '—'],
    ['3.2 总体设计', '推理撰写', '—', '—', '—'],
    ['投标函', '—', '—', '—', '—'],
  ]
  const t = guideTree(single, rows, false)

  it('叶子命中保留祖先链；未命中的兄弟剔除', () => {
    const out = pruneTree(t, (n) => n.label === '3.2 总体设计')
    expect(out).toHaveLength(1)
    expect(out[0].label).toBe('第三章 落实方案')
    expect(out[0].children.map((c) => c.label)).toEqual(['3.2 总体设计'])
    // 裁剪产生新对象，不改原树
    expect(t[0].children).toHaveLength(2)
  })

  it('容器自身命中即保留整支；无任何命中返回空', () => {
    const all = pruneTree(t, () => true)
    expect(all).toHaveLength(2)
    expect(all[0].children).toHaveLength(2)
    expect(pruneTree(t, () => false)).toEqual([])
  })

  it('祖先是否命中不影响保留（容器未命中、后代命中 → 整链留下）', () => {
    const out = pruneTree(t, (n) => n.label === '投标函')
    expect(out.map((n) => n.label)).toEqual(['投标函'])
  })
})
