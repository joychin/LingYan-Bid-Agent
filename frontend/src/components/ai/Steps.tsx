import type { HTMLAttributes, ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

/** prompt-kit Steps 移植：可折叠步骤块（左侧竖线 bar + 步骤项）。Collapsible 用我们手写原语。 */
export type StepsItemProps = HTMLAttributes<HTMLDivElement>

export function StepsItem({ children, className, ...props }: StepsItemProps) {
  return (
    <div className={cn('text-sm text-muted-foreground', className)} {...props}>
      {children}
    </div>
  )
}

export function StepsTrigger({
  children,
  className,
  leftIcon,
  swapIconOnHover = true,
  ...props
}: HTMLAttributes<HTMLButtonElement> & {
  leftIcon?: ReactNode
  swapIconOnHover?: boolean
}) {
  return (
    <CollapsibleTrigger
      className={cn(
        'group flex w-full cursor-pointer items-center justify-start gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground',
        className,
      )}
      {...props}
    >
      <div className="flex items-center gap-2">
        {leftIcon ? (
          <span className="relative inline-flex size-4 items-center justify-center">
            <span className={cn('transition-opacity', swapIconOnHover && 'group-hover:opacity-0')}>
              {leftIcon}
            </span>
            {swapIconOnHover && (
              <ChevronDown className="absolute size-4 opacity-0 transition-opacity group-hover:opacity-100 group-data-[state=open]:rotate-180" />
            )}
          </span>
        ) : null}
        <span>{children}</span>
      </div>
      {!leftIcon && (
        <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
      )}
    </CollapsibleTrigger>
  )
}

export function StepsContent({
  children,
  className,
  bar,
}: HTMLAttributes<HTMLDivElement> & { bar?: ReactNode }) {
  return (
    <CollapsibleContent className={cn('overflow-hidden', className)}>
      <div className="mt-3 grid max-w-full min-w-0 grid-cols-[min-content_minmax(0,1fr)] items-start gap-x-3">
        <div className="min-w-0 self-stretch">{bar ?? <StepsBar />}</div>
        <div className="min-w-0 space-y-2">{children}</div>
      </div>
    </CollapsibleContent>
  )
}

export function StepsBar({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn('h-full w-[2px] bg-muted', className)} {...props} />
}

export function Steps({
  defaultOpen = true,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & { defaultOpen?: boolean }) {
  return <Collapsible className={className} defaultOpen={defaultOpen} {...props} />
}
