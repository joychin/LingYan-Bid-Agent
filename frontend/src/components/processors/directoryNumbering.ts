/**
 * 章节编号预览（2026-09-12）：合册编号逻辑（sidecar docx_ops._HeadingNumberer）
 * 的前端移植 + 目录树装饰纯函数。编号=树位置的纯函数，预览与生成整本同规则：
 * 封面（树首一级叶子名为「封面」）不占号、每册从首章重起、容器节点照常编号。
 * 纯显示层——节点名仍存裸名，目录树不带编号的红线不破；真实合册会跳过未产出
 * 文件的格式件节（不占号），预览按当前树全量编号，此「计划 vs 实际」差异有意接受。
 */

import type { DirectoryData, EditNode } from './directoryTree'

export type NumberingValue = NonNullable<DirectoryData['numbering']>

/** 章节编号格式下拉项（label=格式示意） */
export const NUMBERING_OPTIONS: Array<{ value: NumberingValue; label: string }> = [
  { value: 'chapter', label: '第一章 + 1.1' },
  { value: 'decimal', label: '1 + 1.1' },
  { value: 'gov', label: '一、（一）1.' },
  { value: 'none', label: '不编号' },
]

const CN_DIGITS = '一二三四五六七八九'

/** 1–99 → 中文数字（十、十一、二十一…）；超范围回落阿拉伯数字（章节数到不了）。 */
function cnNum(n: number): string {
  if (!Number.isInteger(n) || n < 1 || n > 99) return String(n)
  if (n < 10) return CN_DIGITS[n - 1]!
  const tens = Math.floor(n / 10)
  const ones = n % 10
  const head = tens === 1 ? '十' : `${CN_DIGITS[tens - 1]}十`
  return head + (ones ? CN_DIGITS[ones - 1]! : '')
}

/** 编号器：prefix(depth) 消费一个 depth 级序号并重置更深计数（depth 1–9，越界返回空）。 */
export function createNumberer(scheme: NumberingValue): { prefix: (depth: number) => string } {
  const s = scheme === 'decimal' || scheme === 'gov' || scheme === 'none' ? scheme : 'chapter'
  const counters: number[] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] // 下标 1 起
  return {
    prefix(depth: number): string {
      if (s === 'none' || !Number.isInteger(depth) || depth < 1 || depth > 9) return ''
      counters[depth]! += 1
      for (let d = depth + 1; d <= 9; d++) counters[d] = 0
      if (s === 'gov') {
        if (depth === 1) return `${cnNum(counters[1]!)}、`
        if (depth === 2) return `（${cnNum(counters[2]!)}）`
        return `${counters[depth]!}.`
      }
      if (s === 'chapter' && depth === 1) return `第${cnNum(counters[1]!)}章\u3000`
      return (
        Array.from({ length: depth }, (_, i) => String(counters[i + 1]!)).join('.') + ' '
      )
    },
  }
}

/** 装饰树节点：node 保持原引用；prefix=编号前缀（不编号/封面=空串，渲染侧跳过）。 */
export interface NumberedNode {
  node: EditNode
  prefix: string
  children: NumberedNode[]
}

/** 名称对账公共分母（对齐 sidecar sanitize_name 的空白折叠；封面判定用）。 */
function cleanName(title: string): string {
  return (title ?? '').replace(/\s+/g, ' ').trim()
}

/**
 * 目录树 → 编号装饰树（纯函数，不改入参）。每册调一次（编号从首章重起）；
 * 树首一级叶子且名为「封面」不占号（合册同口径），其后章节仍从第一章起。
 */
export function numberTree(nodes: EditNode[], scheme: NumberingValue): NumberedNode[] {
  const numberer = createNumberer(scheme)
  const walk = (list: EditNode[], depth: number): NumberedNode[] =>
    list.map((n, i) => {
      const children = n.children ?? []
      const isCover =
        depth === 1 && i === 0 && children.length === 0 && cleanName(n.目录名称) === '封面'
      return {
        node: n,
        prefix: isCover ? '' : numberer.prefix(depth),
        children: children.length ? walk(children, depth + 1) : [],
      }
    })
  return walk(nodes, 1)
}
