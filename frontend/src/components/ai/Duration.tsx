import { useEffect, useState } from 'react'
import { cn, formatDuration } from '@/lib/utils'

/** 步骤耗时：运行中每秒跳动，完成后定格。轻量 interval（卡片数量级 <20 可接受）。 */
export function Duration({
  startedAt,
  endedAt,
  className,
}: {
  startedAt?: number | null
  endedAt?: number | null
  className?: string
}) {
  const [, tick] = useState(0)
  const running = !endedAt
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [running])
  if (!startedAt) return null
  const text = formatDuration((endedAt ?? Date.now()) - startedAt)
  if (!text) return null
  return (
    <span className={cn('shrink-0 text-[11px] tabular-nums text-muted-foreground/50', className)}>
      {text}
    </span>
  )
}
