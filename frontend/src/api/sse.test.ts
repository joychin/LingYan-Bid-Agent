/**
 * sse.ts 全局单槽订阅测试：任意时刻至多一条 SSE 连接（每域名 6 连接预算防线）。
 * fetch-event-source 与 getSidecarInfo 均 mock，只测订阅槽位的 abort 语义。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { getSidecarInfo } from './client'
import { subscribeSSE } from './sse'

vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: vi.fn(() => new Promise(() => {})),
}))
vi.mock('./client', () => ({
  getSidecarInfo: vi.fn(async () => ({ baseURL: '', token: null })),
}))

/** 等订阅 IIFE 内的 await getSidecarInfo 微任务链走完 */
const flush = () => new Promise((r) => setTimeout(r, 0))

describe('subscribeSSE 全局单槽', () => {
  beforeEach(() => {
    vi.mocked(fetchEventSource).mockClear()
    vi.mocked(getSidecarInfo).mockClear()
  })

  it('跨会话重订阅掐掉旧订阅', async () => {
    const a = subscribeSSE('c1', { onEvent: vi.fn() })
    await flush() // 先让第一条完成建连，再订阅第二条（否则旧订阅在 getSidecarInfo 空窗被守卫拦下，不产生连接）
    const b = subscribeSSE('c2', { onEvent: vi.fn() })
    await flush()
    expect(a.signal.aborted).toBe(true)
    expect(b.signal.aborted).toBe(false)
    expect(fetchEventSource).toHaveBeenCalledTimes(2)
    expect(vi.mocked(fetchEventSource).mock.calls[1]?.[0]).toContain('/api/conversations/c2/events')
  })

  it('同会话重复订阅同样先掐旧', async () => {
    const a = subscribeSSE('c1', { onEvent: vi.fn() })
    await flush()
    const b = subscribeSSE('c1', { onEvent: vi.fn() })
    await flush()
    expect(a.signal.aborted).toBe(true)
    expect(b.signal.aborted).toBe(false)
    expect(fetchEventSource).toHaveBeenCalledTimes(2)
  })

  it('订阅先 abort 再拿到 sidecar 地址：不建连（StrictMode 竞态守卫）', async () => {
    let resolveInfo!: (v: { baseURL: string; token: string | null }) => void
    vi.mocked(getSidecarInfo).mockImplementationOnce(
      () => new Promise((r) => (resolveInfo = r)),
    )
    const ctrl = subscribeSSE('c1', { onEvent: vi.fn() })
    ctrl.abort()
    resolveInfo({ baseURL: '', token: null })
    await flush()
    expect(fetchEventSource).not.toHaveBeenCalled()
  })
})

/** 取最近一次 fetchEventSource 调用的 options（结构化子集，避免依赖库内部类型）。 */
interface FesMsg {
  event: string
  data: string
}
interface FesOpts {
  onopen?: (res: Response) => Promise<void>
  onmessage?: (msg: FesMsg) => void
  onerror?: (err: unknown) => number | null | undefined
}
const lastOpts = (): FesOpts =>
  vi.mocked(fetchEventSource).mock.lastCall![1] as unknown as FesOpts

describe('SSE 协议处理', () => {
  beforeEach(() => {
    vi.mocked(fetchEventSource).mockClear()
    vi.mocked(getSidecarInfo).mockClear()
  })

  it('非法 JSON 数据静默跳过，不炸订阅、不回调 onEvent', async () => {
    const onEvent = vi.fn()
    subscribeSSE('c1', { onEvent })
    await flush()
    lastOpts().onmessage!({ event: 'agent.token', data: '{not-json' })
    lastOpts().onmessage!({
      event: 'agent.token',
      data: JSON.stringify({ run_id: 'r1', conversation_id: 'c1', text: 'x' }),
    })
    expect(onEvent).toHaveBeenCalledTimes(1)
  })

  it('ping 与空事件名不透传 onEvent', async () => {
    const onEvent = vi.fn()
    subscribeSSE('c1', { onEvent })
    await flush()
    lastOpts().onmessage!({ event: 'ping', data: '{}' })
    lastOpts().onmessage!({ event: '', data: '{}' })
    expect(onEvent).not.toHaveBeenCalled()
  })

  it('onopen 非 ok 抛出带 status 的错误', async () => {
    subscribeSSE('c1', { onEvent: vi.fn() })
    await flush()
    await expect(
      lastOpts().onopen!({ ok: false, status: 503 } as unknown as Response),
    ).rejects.toThrow('503')
  })

  it('onerror 指数退避（1s 起、封顶 15s），onopen 成功后归零', async () => {
    const onError = vi.fn()
    subscribeSSE('c1', { onEvent: vi.fn(), onError })
    await flush()
    const opts = lastOpts()
    expect(opts.onerror!(new Error('boom'))).toBe(1000)
    expect(opts.onerror!(new Error('boom'))).toBe(2000)
    for (let i = 0; i < 10; i++) opts.onerror!(new Error('boom'))
    expect(opts.onerror!(new Error('boom'))).toBe(15000)
    // 建连成功：退避归零（断线风暴恢复后不沿用长间隔）
    await opts.onopen!({ ok: true, status: 200 } as unknown as Response)
    expect(opts.onerror!(new Error('boom'))).toBe(1000)
  })

  it('404 停连：onerror 原样抛出（不返回重连间隔），不经 onError 重复回调', async () => {
    const onError = vi.fn()
    subscribeSSE('c1', { onEvent: vi.fn(), onError })
    await flush()
    const err = new Error('SSE 打开失败: 404') as Error & { status?: number }
    err.status = 404
    expect(() => lastOpts().onerror!(err)).toThrow(err)
    expect(onError).not.toHaveBeenCalled()
  })
})
