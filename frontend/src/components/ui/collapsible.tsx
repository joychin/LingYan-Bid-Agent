import { createContext, useContext, useState } from 'react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** 轻量手写 Collapsible（prompt-kit Steps/Reasoning 风格组件依赖；零 radix，data-state 语义与 radix 对齐）。
 *  内容 once-open 挂载：折叠内容首次展开后才渲染——长会话里默认收起的折叠组（工具
 *  详情/思考/子代理展开区）不再把全文常驻 DOM（grid 0fr 只是视觉折叠，children 照样
 *  挂载）；展开过之后保持挂载，此后收起的过渡动画仍有效（首开无动画，可接受）。 */
const CollapsibleCtx = createContext<{ open: boolean; toggle: () => void; mounted: boolean }>({
  open: true,
  toggle: () => {},
  mounted: true,
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
  const [everOpened, setEverOpened] = useState(open)
  // 渲染期派生态调整（React 官方模式）：外部受控 open 也可能直接转 true（如
  // useAutoCollapse 之外的程序化展开），不只在 toggle 里能观察到
  if (open && !everOpened) setEverOpened(true)
  const toggle = () => {
    if (controlled === undefined) setInternal((v) => !v)
    onOpenChange?.(!open)
  }
  return (
    <CollapsibleCtx.Provider value={{ open, toggle, mounted: everOpened }}>
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
  const { open, mounted } = useContext(CollapsibleCtx)
  return (
    <div
      data-state={open ? 'open' : 'closed'}
      className={cn('grid transition-[grid-template-rows] duration-200 ease-out', className)}
      style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
      {...props}
    >
      <div className="overflow-hidden">{mounted ? children : null}</div>
    </div>
  )
}
