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
  onerror?: (err: unknown) => void
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

  it('onerror 恒抛出（重连节奏与地址重解析由外层循环掌控），错误原样透传', async () => {
    subscribeSSE('c1', { onEvent: vi.fn() })
    await flush()
    const err = new Error('boom')
    expect(() => lastOpts().onerror!(err)).toThrow(err)
  })

  it('断线重连时重新解析 sidecar 地址（重启换端口/token 后自愈）', async () => {
    vi.useFakeTimers()
    try {
      let infoCalls = 0
      vi.mocked(getSidecarInfo).mockImplementation(
        async () => ({ baseURL: `http://p${++infoCalls}`, token: null }),
      )
      let rejectFirst!: (e: Error) => void
      vi.mocked(fetchEventSource)
        .mockImplementationOnce(() => new Promise((_r, reject) => (rejectFirst = reject)))
        .mockImplementation(() => new Promise(() => {}))
      const ctrl = subscribeSSE('c1', { onEvent: vi.fn() })
      await vi.advanceTimersByTimeAsync(0) // 建连（getSidecarInfo 微任务链）
      expect(fetchEventSource).toHaveBeenCalledTimes(1)
      expect(vi.mocked(fetchEventSource).mock.calls[0]?.[0]).toContain('http://p1')
      rejectFirst(new Error('connection reset'))
      await vi.advanceTimersByTimeAsync(0) // onError + 排定 1s 重试
      expect(fetchEventSource).toHaveBeenCalledTimes(1) // 退避期内未重连
      await vi.advanceTimersByTimeAsync(1000)
      expect(fetchEventSource).toHaveBeenCalledTimes(2)
      expect(vi.mocked(fetchEventSource).mock.calls[1]?.[0]).toContain('http://p2') // 换了新地址
      ctrl.abort()
    } finally {
      vi.useRealTimers()
    }
  })

  it('服务端干净关闭响应体：上报一次错误并重连，不静默终结订阅', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(fetchEventSource)
        .mockImplementationOnce(async () => undefined) // resolve = 干净结束
        .mockImplementation(() => new Promise(() => {}))
      const onError = vi.fn()
      const ctrl = subscribeSSE('c1', { onEvent: vi.fn(), onError })
      await vi.advanceTimersByTimeAsync(0)
      expect(onError).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(1000)
      expect(fetchEventSource).toHaveBeenCalledTimes(2)
      ctrl.abort()
    } finally {
      vi.useRealTimers()
    }
  })

  it('指数退避（1s/2s/4s…），onopen 成功后归零', async () => {
    vi.useFakeTimers()
    try {
      let rejectSecond!: (e: Error) => void
      vi.mocked(fetchEventSource)
        .mockImplementationOnce(() => Promise.reject(new Error('boom')))
        .mockImplementationOnce(() => new Promise((_r, reject) => (rejectSecond = reject)))
        .mockImplementation(() => new Promise(() => {}))
      const ctrl = subscribeSSE('c1', { onEvent: vi.fn() })
      await vi.advanceTimersByTimeAsync(0) // 第 1 次失败 → 排定 1s
      expect(fetchEventSource).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(999)
      expect(fetchEventSource).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(1) // t=1s：第 2 次建连
      expect(fetchEventSource).toHaveBeenCalledTimes(2)
      await lastOpts().onopen!({ ok: true, status: 200 } as unknown as Response) // 退避归零
      rejectSecond(new Error('boom'))
      await vi.advanceTimersByTimeAsync(999)
      expect(fetchEventSource).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(1) // 归零后仍按 1s 重连（未归零则是 2s）
      expect(fetchEventSource).toHaveBeenCalledTimes(3)
      ctrl.abort()
    } finally {
      vi.useRealTimers()
    }
  })

  it('404 停连：错误经 onError 回调一次，此后不再重连', async () => {
    vi.useFakeTimers()
    try {
      const err = new Error('SSE 打开失败: 404') as Error & { status?: number }
      err.status = 404
      vi.mocked(fetchEventSource).mockImplementationOnce(() => Promise.reject(err))
      const onError = vi.fn()
      const ctrl = subscribeSSE('c1', { onEvent: vi.fn(), onError })
      await vi.advanceTimersByTimeAsync(0)
      expect(onError).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(60_000)
      expect(fetchEventSource).toHaveBeenCalledTimes(1) // 终止重连
      ctrl.abort()
    } finally {
      vi.useRealTimers()
    }
  })
})
