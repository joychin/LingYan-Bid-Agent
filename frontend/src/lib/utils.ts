export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(' ')
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

/** 「刚刚 / n 分钟前 / n 小时前 / n 天前」相对时间（§3 会话项、§7 产物卡）。 */
export function formatRelativeTime(iso: string): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  const min = Math.floor(diff / 60_000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hour = Math.floor(min / 60)
  if (hour < 24) return `${hour} 小时前`
  const day = Math.floor(hour / 24)
  if (day < 30) return `${day} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

/** 「8 月 23 日」日期（§5 跨天分隔线）。 */
export function formatDay(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

export type DayBucket = '今天' | '昨天' | '更早'

/** 按 今天/昨天/更早 判定会话分组（§3）。 */
export function dayBucket(iso: string): DayBucket {
  const d = new Date(iso)
  const today = new Date()
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  const startYesterday = startToday - 86_400_000
  const t = d.getTime()
  if (t >= startToday) return '今天'
  if (t >= startYesterday) return '昨天'
  return '更早'
}

/** 毫秒 → 耗时文案："0.8s" / "12s" / "1m 03s" / "2m 41s"。 */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return ''
  const s = ms / 1000
  if (s < 1) return `${s.toFixed(1)}s`
  if (s < 60) return `${Math.floor(s)}s`
  const m = Math.floor(s / 60)
  const rest = Math.floor(s % 60)
  return `${m}m ${String(rest).padStart(2, '0')}s`
}

/** 文本导出为本地文件（右键「另存为」副本下载；Tauri webview 同走 a[download]）。 */
export function downloadText(filename: string, text: string, mime = 'text/markdown') {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  // 同步 revoke 在 WKWebView（Tauri/macOS）会与下载启动竞态吞掉下载——延迟回收
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
