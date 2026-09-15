import { describe, expect, it } from 'vitest'

import { retryNoticeText, retryScopeLabel, retrySecondsLeft } from './retryNotice'

describe('retrySecondsLeft', () => {
  it('未到点按秒递减（ceil 保证显示值 ≥ 实际剩余）', () => {
    const receivedAt = 1_000_000
    expect(retrySecondsLeft(10, receivedAt, receivedAt)).toBe(10)
    expect(retrySecondsLeft(10, receivedAt, receivedAt + 2_500)).toBe(8)
    // elapsed=2.5s、剩 7.5s → ceil=8；边界：恰过 3s → 剩 7
    expect(retrySecondsLeft(10, receivedAt, receivedAt + 3_000)).toBe(7)
  })

  it('归零钳制：等待期过后恒 0（重试已发出、在等响应）', () => {
    const receivedAt = 1_000_000
    expect(retrySecondsLeft(10, receivedAt, receivedAt + 10_000)).toBe(0)
    expect(retrySecondsLeft(10, receivedAt, receivedAt + 60_000)).toBe(0)
  })

  it('旧载荷 waitSeconds=0：恒 0（文案退化为无秒数形态）', () => {
    expect(retrySecondsLeft(0, 1_000_000, 1_000_000)).toBe(0)
  })
})

describe('retryScopeLabel / retryNoticeText', () => {
  it('失败源映射：sub=子代理、main=主线程', () => {
    expect(retryScopeLabel('sub')).toBe('子代理')
    expect(retryScopeLabel('main')).toBe('主线程')
  })

  it('有剩余秒数带「Ns 后」尾巴，归零只剩省略号', () => {
    expect(retryNoticeText({ attempt: 1, total: 3, scope: 'sub', secondsLeft: 8 })).toBe(
      '模型服务不稳，正在自动重试（第 1/3 次 · 子代理） · 8s 后…',
    )
    expect(retryNoticeText({ attempt: 3, total: 3, scope: 'main', secondsLeft: 0 })).toBe(
      '模型服务不稳，正在自动重试（第 3/3 次 · 主线程）…',
    )
  })
})
