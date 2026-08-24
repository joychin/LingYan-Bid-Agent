import type { CSSProperties, ElementType, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** prompt-kit TextShimmer：渐变位移文字（流式/思考态强调）。无第三方依赖。 */
export function TextShimmer({
  as = 'span',
  duration = 4,
  spread = 20,
  children,
  className,
  ...props
}: {
  as?: ElementType
  duration?: number
  spread?: number
  children?: ReactNode
  className?: string
} & Record<string, unknown>) {
  const dynamicSpread = Math.min(Math.max(spread, 5), 45)
  const Component = as as ElementType

  return (
    <Component
      className={cn('text-shimmer font-medium', className)}
      style={
        {
          backgroundImage: `linear-gradient(to right, var(--muted-foreground) ${50 - dynamicSpread}%, var(--foreground) 50%, var(--muted-foreground) ${50 + dynamicSpread}%)`,
          animationDuration: `${duration}s`,
        } as CSSProperties
      }
      {...props}
    >
      {children}
    </Component>
  )
}
