/**
 * createAutoSaveCore 竞态用例（纯状态机，不绑 React；node 环境直测）。
 * 覆盖：防抖触发 / inflight 串行化+续存（保存期间新改动不误报已保存）/
 * 409 → conflict / force 裁决 / reset 换基底 / 挂起的 force 请求在完成后立即续存。
 */

import { describe, expect, it, vi } from 'vitest'
import { createAutoSaveCore, type AutoSaveState } from './useAutoSave'

/** 手动时钟：core 的 timers 注入点，测试逐步推进 */
function manualTimers() {
  let seq = 0
  const pending = new Map<number, () => void>()
  return {
    setTimeout: (fn: () => void, _ms: number) => {
      const id = ++seq
      pending.set(id, fn)
      return id
    },
    clearTimeout: (t: unknown) => {
      pending.delete(t as number)
    },
    tick: () => {
      const fns = [...pending.values()]
      pending.clear()
      fns.forEach((f) => f())
    },
  }
}

function err409(): Error & { status?: number } {
  const e = new Error('内容已被其他修改更新') as Error & { status?: number }
  e.status = 409
  return e
}

function recordStates(core: ReturnType<typeof createAutoSaveCore<number>>): AutoSaveState[] {
  const states: AutoSaveState[] = [core.state]
  core.onStateChange((s) => states.push(s))
  return states
}

describe('createAutoSaveCore', () => {
  it('markDirty 后防抖到期才保存，防抖窗口内重复输入只保存一次', async () => {
    const timers = manualTimers()
    const save = vi.fn(async () => 2)
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers })
    core.markDirty()
    core.markDirty()
    core.markDirty()
    expect(save).not.toHaveBeenCalled()
    timers.tick()
    expect(save).toHaveBeenCalledTimes(1)
    await vi.waitFor(() => expect(core.state).toBe('saved'))
    expect(core.version).toBe(2)
  })

  it('inflight 串行化：保存进行中的防抖到期被挂起，完成后续存（不并发两个保存）', async () => {
    const timers = manualTimers()
    let resolveFirst: (v: number) => void = () => {}
    const save = vi.fn(
      () =>
        new Promise<number>((r) => {
          resolveFirst = r
        }),
    )
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers })

    core.markDirty()
    timers.tick() // 发起保存#1（挂起）
    expect(save).toHaveBeenCalledTimes(1)
    expect(core.state).toBe('saving')

    core.markDirty() // 保存#1 进行中又有改动
    timers.tick() // 防抖到期 → 被 inflight 挡下（挂起）
    expect(save).toHaveBeenCalledTimes(1)

    resolveFirst(2) // 保存#1 成功：期间有新改动 → 保持 dirty，不误报已保存
    await vi.waitFor(() => expect(core.state).toBe('dirty'))
    timers.tick() // 续存的防抖到期 → 保存#2
    expect(save).toHaveBeenCalledTimes(2)
    resolveFirst(3)
    await vi.waitFor(() => expect(core.state).toBe('saved'))
    expect(core.version).toBe(3)
  })

  it('409 → conflict（dirty 保持）；force 裁决成功后清干净', async () => {
    const timers = manualTimers()
    const save = vi.fn(async (force: boolean) => {
      if (!force) throw err409()
      return 5
    })
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers })
    core.markDirty()
    timers.tick()
    await vi.waitFor(() => expect(core.state).toBe('conflict'))
    expect(save).toHaveBeenCalledWith(false)

    const ok = await core.saveNow(true) // 用户裁决「保留我的」
    expect(ok).toBe(true)
    expect(core.state).toBe('saved')
    expect(core.version).toBe(5)
  })

  it('保存期间的 force 请求（用户裁决）被挂起，完成后立即 force 续存', async () => {
    const timers = manualTimers()
    let resolveFirst: (v: number) => void = () => {}
    const forces: boolean[] = []
    const save = vi.fn(
      (force: boolean) =>
        new Promise<number>((r) => {
          forces.push(force)
          resolveFirst = r
        }),
    )
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers })

    core.markDirty()
    timers.tick() // 保存#1（非 force，挂起）
    void core.saveNow(true) // #1 进行中用户点「保留我的」→ 挂起
    expect(save).toHaveBeenCalledTimes(1)

    resolveFirst(2)
    // 挂起的 force 应立即续存（不等防抖）
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2))
    expect(forces).toEqual([false, true])
    resolveFirst(3)
    await vi.waitFor(() => expect(core.state).toBe('saved'))
  })

  it('网络错误 → error 态可重试；防抖期间 error 不再自动触发（等用户或新输入）', async () => {
    const timers = manualTimers()
    let fail = true
    const save = vi.fn(async () => {
      if (fail) throw new Error('network down')
      return 9
    })
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers })
    core.markDirty()
    timers.tick()
    await vi.waitFor(() => expect(core.state).toBe('error'))

    fail = false
    const ok = await core.saveNow() // 点击重试
    expect(ok).toBe(true)
    expect(core.state).toBe('saved')
  })

  it('reset 换基底：清 dirty 回 saved（拉取最新/恢复点恢复路径）', async () => {
    const timers = manualTimers()
    const save = vi.fn(async () => 2)
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers })
    core.markDirty()
    core.reset(7)
    expect(core.state).toBe('saved')
    expect(core.version).toBe(7)
    timers.tick() // 防抖已被 reset 清掉
    expect(save).not.toHaveBeenCalled()
  })

  it('状态变迁经 onStateChange 订阅通知（hook 薄壳依赖的契约）', async () => {
    const timers = manualTimers()
    const save = vi.fn(async () => 2)
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers })
    const states = recordStates(core)
    core.markDirty()
    timers.tick()
    await vi.waitFor(() => expect(core.state).toBe('saved'))
    expect(states).toEqual(['idle', 'dirty', 'saving', 'saved'])
  })

  it('beforeSave 闸拦截：防抖到期不发起保存，保持 dirty（行数漂移确认等场景）', () => {
    const timers = manualTimers()
    const save = vi.fn(async () => 2)
    const beforeSave = vi.fn(() => false)
    const core = createAutoSaveCore<number>({ save, initialVersion: 1, debounceMs: 800, timers, beforeSave })
    core.markDirty()
    timers.tick()
    expect(beforeSave).toHaveBeenCalledTimes(1)
    expect(save).not.toHaveBeenCalled()
    expect(core.state).toBe('dirty') // 不进 saving，等待用户确认
  })
})
