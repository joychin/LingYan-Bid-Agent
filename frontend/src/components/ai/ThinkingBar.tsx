import { ChevronRight } from 'lucide-react'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { cn } from '@/lib/utils'

/** prompt-kit ThinkingBar 移植：微光「Thinking」文字 + 可选 chevron（可点击）/ 停止钮。 */
export function ThinkingBar({
  className,
  text = 'Thinking',
  onStop,
  stopLabel = 'Answer now',
  onClick,
}: {
  className?: string
  text?: string
  onStop?: () => void
  stopLabel?: string
  onClick?: () => void
}) {
  return (
    <div className={cn('flex w-full items-center justify-between', className)}>
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          className="flex items-center gap-1 text-sm transition-opacity hover:opacity-80"
        >
          <TextShimmer className="font-medium">{text}</TextShimmer>
          <ChevronRight className="size-4 text-muted-foreground" />
        </button>
      ) : (
        <TextShimmer className="cursor-default font-medium">{text}</TextShimmer>
      )}
      {onStop ? (
        <button
          type="button"
          onClick={onStop}
          className="border-b border-dotted text-sm text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
          style={{ borderColor: 'var(--muted-foreground)' }}
        >
          {stopLabel}
        </button>
      ) : null}
    </div>
  )
}
