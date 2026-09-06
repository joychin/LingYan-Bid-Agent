import { useSyncExternalStore } from 'react'

/** 会话未读集合（侧栏「新结果待看」圆点）：
 *  - run 在后台走到终态且当时不在该会话内 → 记未读（Sidebar 轮询 diff 调 markUnread）；
 *  - 点击进入该会话 → 清除（markRead）。
 *  localStorage 持久（刷新/重启窗口不丢）；应用整体关闭期间完成的 run 不产生未读
 *  （无事件可回放，恢复后不补历史）——这是「刚完成」的瞬时提示，不是 inbox 式未读。 */

const KEY = 'tender-agent.unread-convs'

function load(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

let state: Set<string> = load()
const listeners = new Set<() => void>()

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify([...state]))
  } catch {
    /* 写失败（隐私模式等）可容忍：未读退化为内存态 */
  }
}

function emit() {
  for (const fn of listeners) fn()
}

export function markUnread(convId: string) {
  if (state.has(convId)) return
  state = new Set(state).add(convId)
  persist()
  emit()
}

export function markRead(convId: string) {
  if (!state.has(convId)) return
  const next = new Set(state)
  next.delete(convId)
  state = next
  persist()
  emit()
}

/** 删除会话/任务时清掉未读残留（被删 id 不再永久滞留集合）。 */
export function forgetConvs(convIds: string[]) {
  const next = new Set(state)
  let changed = false
  for (const id of convIds) changed = next.delete(id) || changed
  if (!changed) return
  state = next
  persist()
  emit()
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** 非 hook 读取器（测试与命令式场景用）；React 组件请走 useUnreadConvs。 */
export function getUnreadConvs(): ReadonlySet<string> {
  return state
}

export function useUnreadConvs(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, getUnreadConvs)
}
