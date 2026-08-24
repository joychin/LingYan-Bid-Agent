import { useEffect, useRef, useState } from 'react'
import { useSidecarHealth } from '@/context/SidecarHealth'

/** §11 sidecar 三色状态条：黄=重连中，绿=已恢复（2s 消失），红=失败（带重试）。 */
export function SidecarBanner() {
  const { status, retry } = useSidecarHealth()
  const [restored, setRestored] = useState(false)
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
      <div className="flex items-center gap-2 border-b bg-warning/10 px-4 py-1.5 text-xs text-warning">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" />
        连接中断，正在重连…
      </div>
    )
  }
  if (status === 'failed') {
    return (
      <div className="flex items-center gap-2 border-b bg-error/10 px-4 py-1.5 text-xs text-error">
        <span className="h-1.5 w-1.5 rounded-full bg-error" />
        服务启动失败
        <button type="button" className="hover:underline" onClick={retry}>
          重试
        </button>
      </div>
    )
  }
  if (restored) {
    return (
      <div className="flex items-center gap-2 border-b bg-success/10 px-4 py-1.5 text-xs text-success">
        <span className="h-1.5 w-1.5 rounded-full bg-success" />
        已恢复连接
      </div>
    )
  }
  return null
}
