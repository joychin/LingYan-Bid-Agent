import { createContext, useContext, useRef, useState } from 'react'
import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** 轻量手写 HoverCard（prompt-kit Source 依赖；零 radix，CSS hover + 延时）。 */
const HoverCardCtx = createContext<{ open: boolean }>({ open: false })

export function HoverCard({
  openDelay = 150,
  closeDelay = 0,
  className,
  children,
}: {
  openDelay?: number
  closeDelay?: number
  className?: string
  children?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(true), openDelay)
  }
  const hide = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(false), closeDelay)
  }

  return (
    <HoverCardCtx.Provider value={{ open }}>
      <div className={cn('relative inline-flex', className)} onMouseEnter={show} onMouseLeave={hide}>
        {children}
      </div>
    </HoverCardCtx.Provider>
  )
}

export function HoverCardTrigger({ children }: { children: ReactNode }) {
  return <>{children}</>
}

export function HoverCardContent({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  const { open } = useContext(HoverCardCtx)
  if (!open) return null
  return (
    <div
      className={cn(
        'absolute left-1/2 top-full z-50 mt-2 w-80 -translate-x-1/2 rounded-lg border bg-popover text-popover-foreground shadow-lg',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
