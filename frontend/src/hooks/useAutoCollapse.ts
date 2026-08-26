import { useEffect, useState } from 'react'
import type { ToolStep } from '@/api/sse'

/** 工具步骤的折叠态：初始「运行中/失败展开、成功收起」；status 变 done/paused 时自动收起。
 *  用户手动展开不会被覆盖（effect 只在状态切换触发）；error 保持展开便于查看。 */
export function useAutoCollapse(status: ToolStep['status']) {
  const [open, setOpen] = useState(status !== 'done' && status !== 'paused')
  useEffect(() => {
    if (status === 'done' || status === 'paused') setOpen(false)
  }, [status])
  return [open, setOpen] as const
}
