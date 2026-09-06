import { useEffect, useRef, useState } from 'react'
import { useSidecarHealth } from '@/context/SidecarHealth'
import { useToast } from '@/context/Toast'
import { exportDiagnostics, isTauri, revealSidecarLogs } from '@/api/client'
import { sidecarFailureTitle } from '@/lib/sidecarFailure'

/** §11 sidecar 三色状态条：黄=重连中，绿=已恢复（2s 消失），红=失败（真重启/日志/诊断）。 */
export function SidecarBanner() {
  const { status, retry, failure } = useSidecarHealth()
  const { toast } = useToast()
  const [restored, setRestored] = useState(false)
  const [busy, setBusy] = useState(false)
  const prev = useRef<ReturnType<typeof useSidecarHealth>['status']>('ok')

  useEffect(() => {
    if (prev.current !== 'ok' && status === 'ok') {
      setRestored(true)
      const t = setTimeout(() => setRestored(false), 2000)
      return () => clearTimeout(t)
    }
    prev.current = status
  }, [status])

  if (status === 'reconnecting') {
    return (
      <div className="sidecar-banner flex items-center gap-2 border-b bg-warning/10 px-4 py-1.5 text-xs text-warning">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" />
        连接中断，正在重连…
      </div>
    )
  }
  if (status === 'failed') {
    const reportError = (e: unknown) => toast(e instanceof Error ? e.message : String(e), 'error')

    const handleRestart = async () => {
      setBusy(true)
      try {
        await retry()
      } finally {
        setBusy(false)
      }
    }

    const exportReport = async () => {
      try {
        const path = await exportDiagnostics()
        if (path) await revealSidecarLogs()
        toast(path ? '诊断报告已导出' : '仅桌面版支持导出诊断', path ? 'success' : 'info')
      } catch (e) {
        reportError(e)
      }
    }

    return (
      <div className="sidecar-banner flex items-start gap-2 border-b bg-error/10 px-4 py-1.5 text-xs text-error">
        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-error" />
        <div className="min-w-0 flex-1 py-0.5">
          <div className="font-medium">{sidecarFailureTitle(failure)}</div>
          {failure?.detail && <div className="mt-0.5 text-error/80">{failure.detail}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-3 py-0.5">
          {isTauri() ? (
            <>
              <button
                type="button"
                className="hover:underline disabled:opacity-50 disabled:hover:no-underline"
                disabled={busy}
                onClick={() => void handleRestart()}
              >
                {busy ? '重启中…' : '重试'}
              </button>
              <button type="button" className="hover:underline" onClick={() => void revealSidecarLogs().catch(reportError)}>
                查看日志
              </button>
              <button type="button" className="hover:underline" onClick={() => void exportReport()}>
                导出诊断
              </button>
            </>
          ) : (
            // 浏览器开发模式没有壳进程可重启，保持原探活重试
            <button type="button" className="hover:underline" onClick={() => void retry()}>
              重试
            </button>
          )}
        </div>
      </div>
    )
  }
  if (restored) {
    return (
      <div className="sidecar-banner flex items-center gap-2 border-b bg-success/10 px-4 py-1.5 text-xs text-success">
        <span className="h-1.5 w-1.5 rounded-full bg-success" />
        已恢复连接
      </div>
    )
  }
  return null
}
