import { Children, Fragment, cloneElement, isValidElement } from 'react'
import type { HTMLAttributes, ReactElement, ReactNode } from 'react'
import { ChevronDown, Circle } from 'lucide-react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

/** prompt-kit ChainOfThought 移植：可折叠思考步骤时间线（圆点 + 连接竖线）。Collapsible 用手写原语。 */
export type ChainOfThoughtItemProps = HTMLAttributes<HTMLDivElement>

export function ChainOfThoughtItem({ children, className, ...props }: ChainOfThoughtItemProps) {
  return (
    <div className={cn('text-sm text-muted-foreground', className)} {...props}>
      {children}
    </div>
  )
}

export function ChainOfThoughtTrigger({
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
        'group flex cursor-pointer items-center justify-start gap-1 text-left text-sm text-muted-foreground transition-colors hover:text-foreground',
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
        ) : (
          <span className="relative inline-flex size-4 items-center justify-center">
            <Circle className="size-2 fill-current" />
          </span>
        )}
        <span>{children}</span>
      </div>
      {!leftIcon && (
        <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
      )}
    </CollapsibleTrigger>
  )
}

export function ChainOfThoughtContent({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <CollapsibleContent className={cn('overflow-hidden', className)} {...props}>
      <div className="grid grid-cols-[min-content_minmax(0,1fr)] gap-x-4">
        <div className="ml-1.75 h-full w-px bg-primary/20 group-data-[last=true]:hidden" />
        <div className="ml-1.75 h-full w-px bg-transparent group-data-[last=false]:hidden" />
        <div className="mt-2 space-y-2">{children}</div>
      </div>
    </CollapsibleContent>
  )
}

export function ChainOfThought({ children, className }: { children: ReactNode; className?: string }) {
  const childrenArray = Children.toArray(children)
  return (
    <div className={cn('space-y-0', className)}>
      {childrenArray.map((child, index) => (
        <Fragment key={index}>
          {isValidElement(child) &&
            cloneElement(child as ReactElement<ChainOfThoughtStepProps>, {
              isLast: index === childrenArray.length - 1,
            })}
        </Fragment>
      ))}
    </div>
  )
}

export type ChainOfThoughtStepProps = {
  children: ReactNode
  className?: string
  isLast?: boolean
}

export function ChainOfThoughtStep({
  children,
  className,
  isLast = false,
  open,
  defaultOpen,
  onOpenChange,
  ...props
}: ChainOfThoughtStepProps &
  HTMLAttributes<HTMLDivElement> & {
    open?: boolean
    defaultOpen?: boolean
    onOpenChange?: (open: boolean) => void
  }) {
  return (
    <Collapsible
      className={cn('group', className)}
      data-last={isLast}
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      {...props}
    >
      {children}
      <div className="flex justify-start group-data-[last=true]:hidden">
        <div className="ml-1.75 h-4 w-px bg-primary/20" />
      </div>
    </Collapsible>
  )
}
