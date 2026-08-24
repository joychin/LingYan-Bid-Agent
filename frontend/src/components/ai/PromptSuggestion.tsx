import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * prompt-kit PromptSuggestion 移植：建议 pill；highlight 模式下整句灰字 + 关键词高亮。
 * 无 cva 依赖（用现有手写 Button），去掉 size="lg"，用我们的 default/sm。
 */
export type PromptSuggestionProps = {
  children: ReactNode
  variant?: 'default' | 'secondary' | 'outline' | 'ghost' | 'destructive'
  size?: 'default' | 'sm' | 'icon'
  className?: string
  highlight?: string
} & ButtonHTMLAttributes<HTMLButtonElement>

export function PromptSuggestion({
  children,
  variant,
  size,
  className,
  highlight,
  ...props
}: PromptSuggestionProps) {
  const isHighlightMode = highlight !== undefined && highlight.trim() !== ''
  const content = typeof children === 'string' ? children : ''

  if (!isHighlightMode) {
    return (
      <Button
        variant={variant ?? 'outline'}
        size={size ?? 'default'}
        className={cn('rounded-full', className)}
        {...props}
      >
        {children}
      </Button>
    )
  }

  if (!content) {
    return (
      <Button
        variant={variant ?? 'ghost'}
        size={size ?? 'sm'}
        className={cn('w-full justify-start rounded-xl py-2 hover:bg-accent', className)}
        {...props}
      >
        {children}
      </Button>
    )
  }

  const trimmed = highlight.trim()
  const idx = content.toLowerCase().indexOf(trimmed.toLowerCase())

  return (
    <Button
      variant={variant ?? 'ghost'}
      size={size ?? 'sm'}
      className={cn('w-full justify-start gap-0 rounded-xl py-2 hover:bg-accent', className)}
      {...props}
    >
      {idx >= 0 ? (
        <>
          {idx > 0 && (
            <span className="whitespace-pre-wrap text-muted-foreground">{content.slice(0, idx)}</span>
          )}
          <span className="whitespace-pre-wrap font-medium text-foreground">
            {content.slice(idx, idx + trimmed.length)}
          </span>
          {idx + trimmed.length < content.length && (
            <span className="whitespace-pre-wrap text-muted-foreground">
              {content.slice(idx + trimmed.length)}
            </span>
          )}
        </>
      ) : (
        <span className="whitespace-pre-wrap text-muted-foreground">{content}</span>
      )}
    </Button>
  )
}
