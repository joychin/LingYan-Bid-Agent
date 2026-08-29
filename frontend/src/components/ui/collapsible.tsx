import { createContext, useContext, useState } from 'react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** 轻量手写 Collapsible（prompt-kit Steps/Reasoning 风格组件依赖；零 radix，data-state 语义与 radix 对齐）。 */
const CollapsibleCtx = createContext<{ open: boolean; toggle: () => void }>({
  open: true,
  toggle: () => {},
})

export function Collapsible({
  open: controlled,
  defaultOpen = true,
  onOpenChange,
  className,
  children,
  ...props
}: {
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
  children?: ReactNode
} & HTMLAttributes<HTMLDivElement>) {
  const [internal, setInternal] = useState(defaultOpen)
  const open = controlled ?? internal
  const toggle = () => {
    if (controlled === undefined) setInternal((v) => !v)
    onOpenChange?.(!open)
  }
  return (
    <CollapsibleCtx.Provider value={{ open, toggle }}>
      <div data-state={open ? 'open' : 'closed'} className={className} {...props}>
        {children}
      </div>
    </CollapsibleCtx.Provider>
  )
}

export function CollapsibleTrigger({
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  const { open, toggle } = useContext(CollapsibleCtx)
  return (
    <button
      type="button"
      data-state={open ? 'open' : 'closed'}
      className={cn('cursor-pointer', className)}
      onClick={toggle}
      {...props}
    >
      {children}
    </button>
  )
}

export function CollapsibleContent({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  const { open } = useContext(CollapsibleCtx)
  return (
    <div
      data-state={open ? 'open' : 'closed'}
      className={cn('grid transition-[grid-template-rows] duration-200 ease-out', className)}
      style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
      {...props}
    >
      <div className="overflow-hidden">{children}</div>
    </div>
  )
}
