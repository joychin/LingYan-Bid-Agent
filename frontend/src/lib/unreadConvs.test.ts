import { describe, expect, it } from 'vitest'
import { getUnreadConvs, markRead, markUnread } from './unreadConvs'

/** store 是模块级单例：每用例用独立 id，先 markRead 兜底保证从零开始。 */
describe('unreadConvs store', () => {
  it('markUnread 记入集合', () => {
    markRead('ua')
    markUnread('ua')
    expect(getUnreadConvs().has('ua')).toBe(true)
  })

  it('重复 markUnread 幂等', () => {
    markRead('ub')
    markUnread('ub')
    markUnread('ub')
    expect(getUnreadConvs().has('ub')).toBe(true)
  })

  it('markRead 清除', () => {
    markUnread('uc')
    markRead('uc')
    expect(getUnreadConvs().has('uc')).toBe(false)
  })
})
