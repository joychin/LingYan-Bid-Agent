/**
 * 版本检查 + 更新提示（2026-09-15，release-management 分支）：
 * 启动静默查一次（成功后 24h 节流）+ 设置页手动查；结果/忽略版本存 localStorage，
 * 派生 hasUpdate 驱动侧栏红点与设置页版本卡。清单拉取走 Rust 壳（fetchLatestRelease，
 * 更新源三层取值见 src-tauri/src/lib.rs），本文件只管节流/缓存/比较/hook。
 *
 * 节流口径：update.lastAt 只记「成功」检查——失败不写，下次启动自动重试；
 * 即每次应用启动最多一次网络请求，成功后 24h 内静默。
 * 忽略口径：只按版本号精确匹配——忽略 v0.1.2 后发布 v0.2.0，红点自然回归。
 */

import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchLatestRelease, isTauri, type LatestReleaseInfo } from '@/api/client'

/** 附检查时间的结果缓存形状（localStorage update.result） */
export interface StoredUpdateResult extends LatestReleaseInfo {
  checkedAt: number
}

export interface UpdateCheckData {
  latest: StoredUpdateResult | null
  ignored: string
}

const LS_LAST_AT = 'update.lastAt'
const LS_RESULT = 'update.result'
const LS_IGNORED = 'update.ignored'
const THROTTLE_MS = 24 * 60 * 60 * 1000
const QUERY_KEY = ['update-check'] as const

/** 版本字符串 → 数值段数组（剥 v/V 前缀；非数字段记 NaN 由调用方判废） */
function parseVersion(v: string): number[] {
  return v
    .trim()
    .replace(/^v/i, '')
    .split('.')
    .map((seg) => (/^\d+$/.test(seg) ? Number.parseInt(seg, 10) : Number.NaN))
}

/** 版本比较：按 `.` 逐段「数值」比较（防 0.10.0 < 0.9.0 的字符串坑），缺段补 0。
    任一段非数字 → false：清单或本地版本不合法时宁可不提示，不误报。 */
export function isNewerVersion(latest: string, current: string): boolean {
  const a = parseVersion(latest)
  const b = parseVersion(current)
  if (a.some(Number.isNaN) || b.some(Number.isNaN)) return false
  const len = Math.max(a.length, b.length)
  for (let i = 0; i < len; i++) {
    const x = a[i] ?? 0
    const y = b[i] ?? 0
    if (x !== y) return x > y
  }
  return false
}

/** 节流判定：上次成功检查落在窗口内 → 本次启动不再联网。 */
export function shouldSkipNetwork(lastAt: number, now: number): boolean {
  return lastAt > 0 && now - lastAt < THROTTLE_MS
}

/** 检查时间的人话相对值（「N 分钟前」），供版本卡「…前检查过」拼接。 */
export function formatCheckedAt(ts: number, now = Date.now()): string {
  const diff = Math.max(0, now - ts)
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return `${Math.floor(diff / 86_400_000)} 天前`
}

function readLastAt(): number {
  const n = Number(localStorage.getItem(LS_LAST_AT))
  return Number.isFinite(n) && n > 0 ? n : 0
}

function readStoredResult(): StoredUpdateResult | null {
  try {
    const raw = localStorage.getItem(LS_RESULT)
    if (!raw) return null
    const obj = JSON.parse(raw) as StoredUpdateResult
    if (typeof obj?.version === 'string' && typeof obj?.url === 'string') return obj
  } catch {
    /* 缓存损坏按无缓存处理 */
  }
  return null
}

function readIgnored(): string {
  return localStorage.getItem(LS_IGNORED) ?? ''
}

function writeIgnored(version: string): void {
  if (version) localStorage.setItem(LS_IGNORED, version)
  else localStorage.removeItem(LS_IGNORED)
}

/** 共享执行体：silent（启动 query）失败静默、不落 error；force（手动）失败带 error
    返回供内联展示。失败都保留旧结果（可能过期）且不写 lastAt。 */
async function runCheck(force: boolean): Promise<UpdateCheckData & { error?: string }> {
  const now = Date.now()
  if (!force) {
    const cached = readStoredResult()
    if (cached && shouldSkipNetwork(readLastAt(), now)) {
      return { latest: cached, ignored: readIgnored() }
    }
  }
  try {
    const info = await fetchLatestRelease()
    const stored: StoredUpdateResult = { ...info, checkedAt: now }
    localStorage.setItem(LS_RESULT, JSON.stringify(stored))
    localStorage.setItem(LS_LAST_AT, String(now))
    return { latest: stored, ignored: readIgnored() }
  } catch (e) {
    const fallback = { latest: readStoredResult(), ignored: readIgnored() }
    if (!force) return fallback
    return { ...fallback, error: e instanceof Error ? e.message : String(e) }
  }
}

export function useUpdateCheck() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async (): Promise<UpdateCheckData> => {
      const r = await runCheck(false)
      return { latest: r.latest, ignored: r.ignored }
    },
    enabled: isTauri(),
    // 组件重挂载 15min 内不重跑；真正的节流闸在 runCheck（成功后 24h）
    staleTime: 15 * 60 * 1000,
    // 缓存跨组件存活：侧栏红点与设置卡读同一份数据，忽略操作全局一致
    gcTime: Infinity,
    retry: false,
  })

  const setIgnored = useCallback(
    (version: string) => {
      writeIgnored(version)
      // 忽略态折进同一份 query 缓存：hasUpdate 的所有消费方（红点/版本卡）同步重算
      queryClient.setQueryData<UpdateCheckData>(QUERY_KEY, (prev) =>
        prev ? { ...prev, ignored: version } : prev,
      )
    },
    [queryClient],
  )

  /** 手动检查（设置页按钮）：绕过节流强制联网；失败保留旧结果并带 error 返回。 */
  const forceCheck = useCallback(async (): Promise<UpdateCheckData & { error?: string }> => {
    if (!isTauri()) return { latest: readStoredResult(), ignored: readIgnored() }
    const r = await runCheck(true)
    queryClient.setQueryData<UpdateCheckData>(QUERY_KEY, { latest: r.latest, ignored: r.ignored })
    return r
  }, [queryClient])

  const latest = query.data?.latest ?? null
  const ignored = query.data?.ignored ?? ''
  const hasUpdate =
    !!latest && isNewerVersion(latest.version, __APP_VERSION__) && latest.version !== ignored

  return {
    latest,
    ignored,
    hasUpdate,
    isChecking: query.isFetching,
    forceCheck,
    /** 忽略当前最新版本（红点消失，版本卡收成一行可恢复） */
    ignore: () => {
      if (latest) setIgnored(latest.version)
    },
    /** 取消忽略（版本卡「仍要查看」） */
    unignore: () => setIgnored(''),
  }
}
