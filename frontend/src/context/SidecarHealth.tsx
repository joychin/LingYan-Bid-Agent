import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  checkHealth,
  getSidecarFailure,
  isTauri,
  restartSidecar,
  type SidecarFailure,
} from '@/api/client'

/** booting=本次会话尚未就绪过（应用启动中）；splash 收尾后 sidecar 已就绪，此态很快收敛 */
export type SidecarStatus = 'booting' | 'ok' | 'reconnecting' | 'failed'

interface SidecarHealthContextValue {
  status: SidecarStatus
  /** 每次成功恢复自增，让 useRun 重挂 SSE（sidecar 换端口后旧连接失效）。 */
  reconnectSeq: number
  /** 最近一次失败原因（仅 failed 态展示；拿不到时前端用兜底文案）。 */
  failure: SidecarFailure | null
  /** 红态「重试」：Tauri 下真重启 sidecar（清熔断计数重新拉起），浏览器模式仅重新探活。 */
  retry: () => Promise<void>
}

const SidecarHealthContext = createContext<SidecarHealthContextValue | null>(null)

const POLL_MS = 4000
const FAIL_LIMIT = 3
/** 首启窗口：从未就绪时探活失败维持 booting 语义（打包模式冷启动可到数十秒，
 * Windows 首启解压+Defender 扫描更慢）；超窗仍从未就绪=大概率真故障，放行走红条。 */
const BOOTING_LIMIT_MS = 90_000

/** 轮询 /api/healthz 驱动 sidecar 四态状态机（§11：booting/ok/reconnecting/failed）。 */
export function SidecarHealthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SidecarStatus>('booting')
  const [reconnectSeq, setReconnectSeq] = useState(0)
  const [failure, setFailure] = useState<SidecarFailure | null>(null)
  const failCount = useRef(0)
  const wasFailed = useRef(false)
  const everOk = useRef(false)
  const mountedAt = useRef(Date.now())
  const queryClient = useQueryClient()

  const probe = useCallback(async () => {
    if (document.hidden) return // 隐藏期不探测（省空转唤醒；回到可见下一次 tick 即恢复）
    const ok = await checkHealth()
    if (ok) {
      everOk.current = true
      // 从非 ok 恢复：递增 reconnectSeq 并复位，同时重拉所有查询（会话/文件/产物/消息）
      if (wasFailed.current) {
        wasFailed.current = false
        setReconnectSeq((s) => s + 1)
        void queryClient.invalidateQueries()
      }
      failCount.current = 0
      setFailure(null)
      setStatus('ok')
    } else {
      // 首启窗口内（本次会话从未就绪）：sidecar 确实在启动而非「中断」，维持 booting
      // 不转黄条吓用户；「正在启动」的语义由 splash 画面 + banner booting 分支承载
      if (!everOk.current && Date.now() - mountedAt.current < BOOTING_LIMIT_MS) {
        setStatus('booting')
        return
      }
      failCount.current += 1
      const failed = failCount.current >= FAIL_LIMIT
      if (failed) {
        wasFailed.current = true
        // 取 Rust supervisor 记录的失败原因（红态期间每次探测刷新一次，跟随最新失败；
        // 本地 IPC 调用开销可忽略）
        void getSidecarFailure()
          .then(setFailure)
          .catch(() => setFailure(null))
      }
      setStatus(failed ? 'failed' : 'reconnecting')
    }
  }, [queryClient])

  useEffect(() => {
    const id = setInterval(probe, POLL_MS)
    return () => clearInterval(id)
  }, [probe])

  const retry = useCallback(async () => {
    if (isTauri()) {
      // 真重启：Rust 侧清零熔断计数并重新拉起；wasFailed 保持 true，
      // 恢复后才会走 reconnectSeq+1 + invalidateQueries 的对账路径
      await restartSidecar().catch(() => undefined)
    }
    failCount.current = 0
    setFailure(null)
    setStatus('reconnecting')
    void probe()
  }, [probe])

  // value 引用稳定（status 等真实变化才换引用）：轮询同值 bail 时不再连带 consumer
  const value = useMemo<SidecarHealthContextValue>(
    () => ({ status, reconnectSeq, failure, retry }),
    [status, reconnectSeq, failure, retry],
  )

  return (
    <SidecarHealthContext.Provider value={value}>
      {children}
    </SidecarHealthContext.Provider>
  )
}

export function useSidecarHealth(): SidecarHealthContextValue {
  const ctx = useContext(SidecarHealthContext)
  if (!ctx) throw new Error('useSidecarHealth must be used within SidecarHealthProvider')
  return ctx
}
