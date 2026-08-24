import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { checkHealth } from '@/api/client'

export type SidecarStatus = 'ok' | 'reconnecting' | 'failed'

interface SidecarHealthContextValue {
  status: SidecarStatus
  /** 每次成功恢复自增，让 useRun 重挂 SSE（sidecar 换端口后旧连接失效）。 */
  reconnectSeq: number
  /** 立即重新探测（§11 红态「重试」）。 */
  retry: () => void
}

const SidecarHealthContext = createContext<SidecarHealthContextValue | null>(null)

const POLL_MS = 4000
const FAIL_LIMIT = 3

/** 轮询 /api/healthz 驱动 sidecar 三色状态机（§11）。 */
export function SidecarHealthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SidecarStatus>('ok')
  const [reconnectSeq, setReconnectSeq] = useState(0)
  const failCount = useRef(0)
  const wasFailed = useRef(false)
  const queryClient = useQueryClient()

  const probe = useCallback(async () => {
    const ok = await checkHealth()
    if (ok) {
      // 从非 ok 恢复：递增 reconnectSeq 并复位，同时重拉所有查询（会话/文件/产物/消息）
      if (wasFailed.current) {
        wasFailed.current = false
        setReconnectSeq((s) => s + 1)
        void queryClient.invalidateQueries()
      }
      failCount.current = 0
      setStatus('ok')
    } else {
      failCount.current += 1
      const failed = failCount.current >= FAIL_LIMIT
      if (failed) wasFailed.current = true
      setStatus(failed ? 'failed' : 'reconnecting')
    }
  }, [queryClient])

  useEffect(() => {
    const id = setInterval(probe, POLL_MS)
    return () => clearInterval(id)
  }, [probe])

  const retry = useCallback(() => {
    failCount.current = 0
    setStatus('reconnecting')
    void probe()
  }, [probe])

  return (
    <SidecarHealthContext.Provider value={{ status, reconnectSeq, retry }}>
      {children}
    </SidecarHealthContext.Provider>
  )
}

export function useSidecarHealth(): SidecarHealthContextValue {
  const ctx = useContext(SidecarHealthContext)
  if (!ctx) throw new Error('useSidecarHealth must be used within SidecarHealthProvider')
  return ctx
}
