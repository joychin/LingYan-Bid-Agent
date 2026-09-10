/**
 * 编辑表面共享的自动保存基建（2026-09-04 编辑基建统一）。
 *
 * 三个编辑表面（DirectoryProcessor / NoteProcessor / WorkbenchViewer）原本各自
 * 实现防抖保存 + 409 裁决 + 轮询探测，且都缺竞态防护。本模块统一：
 *
 * - 防抖自动保存（debounceMs，默认 800ms）；
 * - 竞态防护两层（老工程 useSectionAutoSave 先例）：
 *   ① inflight 串行化——保存进行中的新请求被挂起，完成后按需续存，永不并发
 *     两个保存请求；保存成功但期间又有改动 → 保持 dirty 续存（不误报已保存）；
 *   ② 请求序号守卫——过期的错误响应不回写状态（期间可能已成功保存）；
 * - 外部更新探测（useAutoSave 的轮询）：无本地改动静默跟随（onExternalUpdate，
 *   组件拉最新内容后调 reset）；有本地改动置 conflict，由组件横幅交用户裁决
 *   （「拉取最新」=组件 adopt + reset；「保留我的」=saveNow(true) force 覆盖）。
 *
 * 状态机为纯 core（createAutoSaveCore，不绑 React，vitest 直测竞态场景）；
 * useAutoSave 是薄壳：订阅 core 状态 + 轮询定时器 + 卸载冲刷
 * （挂起保存先常规、失败 force——「主导权归用户」，永不静默丢编辑）。
 *
 * 内容本体在组件 state——core 只管时机与状态：save 闭包从组件 ref 取最新内容。
 * 版本号泛型 V（产物 content_seq: number / 工作台 hash: string），比较按字符串归一。
 * 文件夹语义铁则不变：无锁，版本号是探测器不是锁。
 */

import { useEffect, useRef, useState } from 'react'

export type AutoSaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error' | 'conflict'

export interface AutoSaveSaveFn<V extends string | number> {
  /** 保存（从组件 ref 取最新内容）；成功返回新版本号；抛 {status:409} = 外部更新探测信号 */
  (force: boolean): Promise<V>
}

export interface AutoSaveCore<V extends string | number> {
  readonly state: AutoSaveState
  readonly version: V
  readonly lastSavedAt: number | null
  markDirty(): void
  /** 轮询探测发现外部更新且本地有改动：置 conflict（dirty 保持，等用户裁决） */
  markConflict(): void
  saveNow(force?: boolean): Promise<boolean>
  /** 热替换 save 闭包（hook 每次 render 同步刷新——组件 save 闭包捕获的 props/state 才不致过期） */
  setSave(fn: AutoSaveSaveFn<V>): void
  /** 外部基底切换（拉取最新/恢复点恢复后）：清 dirty 回 saved */
  reset(nextVersion: V): void
  onStateChange(cb: (s: AutoSaveState, lastSavedAt: number | null) => void): () => void
  dispose(): void
}

export function createAutoSaveCore<V extends string | number>(opts: {
  save: AutoSaveSaveFn<V>
  initialVersion: V
  debounceMs?: number
  /** 发起保存前的闸（如机器输入行数漂移确认）：返回 false = 本次不保存，保持 dirty 等待用户 */
  beforeSave?: () => boolean
  /** 供测试注入时钟；生产用 window.setTimeout/clearTimeout */
  timers?: { setTimeout: (fn: () => void, ms: number) => unknown; clearTimeout: (t: unknown) => void }
}): AutoSaveCore<V> {
  const debounceMs = opts.debounceMs ?? 800
  const timers = opts.timers ?? {
    setTimeout: (fn: () => void, ms: number) => window.setTimeout(fn, ms),
    clearTimeout: (t: unknown) => window.clearTimeout(t as number),
  }

  let state: AutoSaveState = 'idle'
  let version = opts.initialVersion
  let lastSavedAt: number | null = null
  let dirty = false
  let reqSeq = 0
  let inflight: Promise<boolean> | null = null
  /** inflight 期间被挡下的保存请求：false=防抖到期（续存走防抖）、true=用户 force（完成后续存立即 force） */
  let forcePending: boolean | null = null
  let resumeNeeded = false
  let timer: unknown = null
  const listeners = new Set<(s: AutoSaveState, t: number | null) => void>()
  const saveRef = { current: opts.save }

  const emit = () => listeners.forEach((cb) => cb(state, lastSavedAt))
  const setState = (s: AutoSaveState) => {
    state = s
    emit()
  }

  const schedule = () => {
    if (timer !== null) timers.clearTimeout(timer)
    timer = timers.setTimeout(() => {
      timer = null
      if (dirty && state !== 'conflict' && state !== 'error' && opts.beforeSave?.() !== false) {
        void doSave(false)
      }
    }, debounceMs)
  }

  const doSave = async (force: boolean): Promise<boolean> => {
    if (inflight) {
      // 串行化：挂起本次请求（force 只升级不降级），由在途保存的 finally 续存
      resumeNeeded = true
      forcePending = forcePending || force
      return inflight
    }
    const seq = ++reqSeq
    const p = (async () => {
      // 闸门统一在 doSave 入口（2026-09-10 review）：saveNow/续存与防抖同闸——
      // 「完成编辑」在 800ms 防抖窗口内不再绕过结构/行数确认条。force=用户显式
      // 裁决（「保留我的」覆盖等）直通。被闸时返回 false、状态不动（保持
      // dirty/error 等用户处理确认条），调用方据此决定是否留在编辑态。
      if (!force && opts.beforeSave?.() === false) {
        return false
      }
      setState('saving')
      try {
        const v = await saveRef.current(force)
        version = v
        if (resumeNeeded) {
          // 保存期间又有改动：内容里已有新版本未含的改动 → 保持 dirty 续存
          setState('dirty')
        } else {
          dirty = false
          lastSavedAt = Date.now()
          setState('saved')
        }
        return true
      } catch (e) {
        const err = e as Error & { status?: number }
        if (err.status === 409) {
          // 探测信号：外部已更新 → 交用户裁决（dirty 保持，内容不入库）
          setState('conflict')
        } else if (seq === reqSeq) {
          // 过期错误响应不回写（期间可能已成功保存/再次发起）
          setState('error')
        }
        return false
      } finally {
        inflight = null
        const pendingForce = forcePending
        if (resumeNeeded) {
          resumeNeeded = false
          forcePending = null
          if (pendingForce) void doSave(true) // 用户显式裁决：立即续存
          else schedule() // 防抖续存（重新等窗口，打字继续则继续重置）
        }
      }
    })()
    inflight = p
    return p
  }

  return {
    get state() {
      return state
    },
    get version() {
      return version
    },
    get lastSavedAt() {
      return lastSavedAt
    },
    markDirty() {
      dirty = true
      setState('dirty')
      schedule()
    },
    markConflict() {
      setState('conflict')
    },
    saveNow(force = false) {
      return doSave(force)
    },
    setSave(fn) {
      saveRef.current = fn
    },
    reset(nextVersion: V) {
      version = nextVersion
      dirty = false
      resumeNeeded = false
      forcePending = null
      if (timer !== null) {
        timers.clearTimeout(timer)
        timer = null
      }
      lastSavedAt = Date.now()
      setState('saved')
    },
    onStateChange(cb) {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    dispose() {
      if (timer !== null) timers.clearTimeout(timer)
      timer = null
      listeners.clear()
    },
  }
}

export interface UseAutoSaveOptions<V extends string | number> {
  save: AutoSaveSaveFn<V>
  /** 轻量探测远端版本号（GET meta 端点，不拉全文/列表） */
  fetchMeta: () => Promise<V>
  initialVersion: V
  /** 编辑/探测总开关（查看态也要跟随外部更新 → 默认常开；conflict/saving 时轮询自动跳过） */
  enabled?: boolean
  debounceMs?: number
  pollMs?: number
  /** 发起保存前的闸（如机器输入行数漂移确认）：返回 false = 本次不保存，保持 dirty 等待用户 */
  beforeSave?: () => boolean
  /** 轮询发现外部更新且无本地改动：静默跟随（组件拉内容后调 reset） */
  onExternalUpdate?: (remoteVersion: V) => void
}

export interface UseAutoSaveHandle<V extends string | number> {
  state: AutoSaveState
  lastSavedAt: number | null
  /** 内容变化时调：置 dirty + 重置防抖 */
  markDirty: () => void
  /** 立即保存（force=用户裁决「保留我的」） */
  saveNow: (force?: boolean) => Promise<boolean>
  /** 外部基底切换（拉取最新/恢复点恢复后）：清 dirty 回 saved */
  reset: (version: V) => void
}

export function useAutoSave<V extends string | number>(opts: UseAutoSaveOptions<V>): UseAutoSaveHandle<V> {
  const { initialVersion, enabled = true, debounceMs = 800, pollMs = 5_000, beforeSave } = opts

  const coreRef = useRef<AutoSaveCore<V> | null>(null)
  if (coreRef.current === null) {
    coreRef.current = createAutoSaveCore<V>({ save: opts.save, initialVersion, debounceMs, beforeSave })
  }
  const core = coreRef.current
  // 每次 render 热替换 save 闭包（core 的 setSave 同步生效）：组件 save 捕获的
  // props/state 不致过期；防抖窗口内的最新内容仍由组件侧 ref 双保险兜底。
  core.setSave(opts.save)
  const saveRef = useRef(opts.save)
  saveRef.current = opts.save

  const [state, setState] = useState<AutoSaveState>(core.state)
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(core.lastSavedAt)

  useEffect(() => {
    const off = core.onStateChange((s, t) => {
      setState(s)
      setLastSavedAt(t)
    })
    return () => {
      off()
      core.dispose()
    }
  }, [core])

  const fetchMetaRef = useRef(opts.fetchMeta)
  fetchMetaRef.current = opts.fetchMeta
  const onExternalRef = useRef(opts.onExternalUpdate)
  onExternalRef.current = opts.onExternalUpdate

  // 外部更新探测：conflict/saving 跳过（saving 期间版本号将随保存前进；conflict 等裁决）。
  // fetchMeta 异步返回后重读状态——期间用户可能已开始编辑（dirty → conflict 裁决而非覆盖）。
  useEffect(() => {
    if (!enabled || pollMs <= 0) return
    const t = window.setInterval(() => {
      const s = core.state
      if (s === 'saving' || s === 'conflict') return
      fetchMetaRef
        .current()
        .then((remote) => {
          if (String(remote) === String(core.version)) return
          if (core.state === 'dirty' || core.state === 'error') core.markConflict()
          else onExternalRef.current?.(remote)
        })
        .catch(() => {})
    }, pollMs)
    return () => window.clearInterval(t)
  }, [enabled, pollMs, core, setState])

  // 卸载冲刷：挂起保存先常规、失败 force（主导权归用户，永不静默丢编辑）
  useEffect(() => {
    return () => {
      if (core.state === 'dirty' || core.state === 'error' || core.state === 'conflict') {
        void saveRef
          .current(false)
          .catch(() => saveRef.current(true))
          .catch(() => {})
      }
    }
  }, [core])

  return {
    state,
    lastSavedAt,
    markDirty: core.markDirty,
    saveNow: core.saveNow,
    reset: core.reset,
  }
}
