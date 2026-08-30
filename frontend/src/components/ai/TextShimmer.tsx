import type { CSSProperties, ElementType, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * prompt-kit TextShimmer：渐变位移文字（流式/思考态强调）。无第三方依赖。
 * 底色用 --shimmer-base（ai.css 按模式取灰阶），高亮带恒为 text-primary——
 * 底灰若取 text-secondary，浅色下与高亮带对比不足，肉眼近乎不可见（2026-08-30 用户反馈）。
 */
export function TextShimmer({
  as = 'span',
  duration = 2.5,
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
      className={cn('text-shimmer', className)}
      style={
        {
          backgroundImage: `linear-gradient(to right, var(--shimmer-base, var(--Color-text-tertiary)) ${50 - dynamicSpread}%, var(--Color-text-primary) 50%, var(--shimmer-base, var(--Color-text-tertiary)) ${50 + dynamicSpread}%)`,
          animationDuration: `${duration}s`,
        } as CSSProperties
      }
      {...props}
    >
      {children}
    </Component>
  )
}
