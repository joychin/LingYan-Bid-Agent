/**
 * sidebarList 纯函数测试：截断基线、例外原位保留、展开全量、
 * 「后段全是例外=无东西可藏」边界。
 */

import { describe, expect, it } from 'vitest'
import { CONV_PREVIEW_LIMIT, pickVisibleConversations } from './sidebarList'

type Conv = { id: string }

/** 造 n 个会话，id 顺序即「最近在前」的列表序（c1 最新）。 */
const convs = (n: number): Conv[] => Array.from({ length: n }, (_, i) => ({ id: `c${i + 1}` }))
const noException = () => false

describe('pickVisibleConversations', () => {
  it('不超限额：全量可见，无隐藏', () => {
    const r = pickVisibleConversations(convs(10), noException, false)
    expect(r.visible).toHaveLength(10)
    expect(r.hiddenCount).toBe(0)
  })

  it('超限额：只留最近 LIMIT 条，hidden 计数正确', () => {
    const all = convs(20)
    const r = pickVisibleConversations(all, noException, false)
    expect(r.visible).toEqual(all.slice(0, CONV_PREVIEW_LIMIT))
    expect(r.hiddenCount).toBe(5)
  })

  it('例外在老位置：原位保留（visible 超限额），hidden 相应减少', () => {
    const all = convs(20) // 设 c18 是运行中/未读等例外
    const r = pickVisibleConversations(all, (c) => c.id === 'c18', false)
    expect(r.visible.map((c) => c.id)).toEqual([
      ...all.slice(0, 15).map((c) => c.id),
      'c18',
    ])
    expect(r.hiddenCount).toBe(4)
  })

  it('例外落在限额内：不重复计入', () => {
    const all = convs(20)
    const r = pickVisibleConversations(all, (c) => c.id === 'c3', false)
    expect(r.visible.map((c) => c.id)).toEqual(all.slice(0, 15).map((c) => c.id))
    expect(r.hiddenCount).toBe(5)
  })

  it('expanded=true：一次全量，无隐藏', () => {
    const all = convs(40)
    const r = pickVisibleConversations(all, noException, true)
    expect(r.visible).toEqual(all)
    expect(r.hiddenCount).toBe(0)
  })

  it('后段全是例外：hiddenCount=0，折叠视图=全量（不应出按钮）', () => {
    const all = convs(20)
    const r = pickVisibleConversations(
      all,
      (c) => Number(c.id.slice(1)) > 15,
      false,
    )
    expect(r.visible).toEqual(all)
    expect(r.hiddenCount).toBe(0)
  })
})
