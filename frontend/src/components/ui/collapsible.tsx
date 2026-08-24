import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** 轻量手写 Collapsible（prompt-kit Steps/ChainOfThought 依赖；零 radix，data-state 语义与 radix 对齐）。 */
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
  const outerRef = useRef<HTMLDivElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const outer = outerRef.current
    const inner = innerRef.current
    if (!outer || !inner) return
    outer.style.maxHeight = open ? `${inner.scrollHeight}px` : '0px'
  }, [open, children])

  return (
    <div
      ref={outerRef}
      data-state={open ? 'open' : 'closed'}
      className={cn('overflow-hidden transition-[max-height] duration-200 ease-out', className)}
      style={{ maxHeight: '0px' }}
      {...props}
    >
      <div ref={innerRef}>{children}</div>
    </div>
  )
}
