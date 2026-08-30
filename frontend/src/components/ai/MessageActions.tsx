import { useCallback, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** 轻量手写 MessageActions（prompt-kit message 移植；零 radix——tooltip 用 CSS
 *  group-hover 淡入实现，同 hover-card.tsx 先例，不 display 切换防抖动）。 */

export type MessageActionsProps = {
  children?: ReactNode
  className?: string
}

/** 消息操作条容器：图标按钮行。显隐（hover 淡入）由调用方加 group 类控制。 */
export function MessageActions({ children, className }: MessageActionsProps) {
  return (
    <div className={cn('flex items-center gap-0.5 text-muted-foreground', className)}>
      {children}
    </div>
  )
}

export type MessageActionProps = {
  /** 悬停提示文案 */
  tooltip: ReactNode
  children: ReactNode
  /** 浮层在触发器上方/下方（操作条贴消息底部，top 不会越出滚动区顶缘） */
  side?: 'top' | 'bottom'
  /** 水平对齐随触发器位置：行首 start、行尾 end，防 chat-scroll 左右缘溢出 */
  align?: 'start' | 'center' | 'end'
  className?: string
  onClick?: () => void
  /** tooltip 非字符串时的无障碍名 */
  ariaLabel?: string
}

/** tooltip 图标按钮（compact 28px，小于通用 Button 的 icon 档）。 */
export function MessageAction({
  tooltip,
  children,
  side = 'top',
  align = 'center',
  className,
  onClick,
  ariaLabel,
}: MessageActionProps) {
  return (
    <span className="group/action relative inline-flex">
      <button
        type="button"
        aria-label={typeof tooltip === 'string' ? tooltip : ariaLabel}
        onClick={onClick}
        className={cn(
          'inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
          className,
        )}
      >
        {children}
      </button>
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 whitespace-nowrap rounded-md border bg-popover px-2 py-1 text-xs text-popover-foreground opacity-0 shadow-md transition-opacity duration-100 group-hover/action:opacity-100',
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
          align === 'start' && 'left-0',
          align === 'center' && 'left-1/2 -translate-x-1/2',
          align === 'end' && 'right-0',
        )}
      >
        {tooltip}
      </span>
    </span>
  )
}

/** prompt-kit useCopyToClipboard 同款小 hook：写剪贴板，copied 置位 timeout 后自动复位。 */
export function useCopyToClipboard({ timeout = 2000 }: { timeout?: number } = {}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text)
      } catch {
        return false
      }
      setCopied(true)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), timeout)
      return true
    },
    [timeout],
  )
  return { copied, copy }
}
