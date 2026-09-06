import { createContext, useContext, useEffect, useState } from 'react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { ChevronDownIcon } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { mdRemarkPlugins } from '@/lib/markdown'
import { cn } from '@/lib/utils'

/**
 * prompt-kit Reasoning 移植：可折叠「深度思考」块；isStreaming 时首次自动展开、结束自动收起。
 * 用 react-markdown 替代 prompt-kit 的 Markdown（同栈，无新依赖）。
 * 内容 once-open 挂载（同 ui/collapsible）：历史消息默认收起的执行过程整棵树
 * （工具详情/思考全文）首次展开前不进 DOM。
 */
const ReasoningContext = createContext<
  { isOpen: boolean; onOpenChange: (open: boolean) => void; mounted: boolean } | undefined
>(undefined)

function useReasoningContext() {
  const ctx = useContext(ReasoningContext)
  if (!ctx) throw new Error('useReasoningContext must be used within a Reasoning provider')
  return ctx
}

export function Reasoning({
  children,
  className,
  open,
  onOpenChange,
  isStreaming,
}: {
  children: ReactNode
  className?: string
  open?: boolean
  onOpenChange?: (open: boolean) => void
  isStreaming?: boolean
}) {
  const [internalOpen, setInternalOpen] = useState(false)
  const [wasAutoOpened, setWasAutoOpened] = useState(false)

  const isControlled = open !== undefined
  const isOpen = isControlled ? open : internalOpen
  const [everOpened, setEverOpened] = useState(false)
  if (isOpen && !everOpened) setEverOpened(true)

  const handleOpenChange = (newOpen: boolean) => {
    if (!isControlled) setInternalOpen(newOpen)
    onOpenChange?.(newOpen)
  }

  useEffect(() => {
    if (isStreaming && !wasAutoOpened) {
      if (!isControlled) setInternalOpen(true)
      setWasAutoOpened(true)
    }
    if (!isStreaming && wasAutoOpened) {
      if (!isControlled) setInternalOpen(false)
      setWasAutoOpened(false)
    }
  }, [isStreaming, wasAutoOpened, isControlled])

  return (
    <ReasoningContext.Provider value={{ isOpen, onOpenChange: handleOpenChange, mounted: everOpened }}>
      <div className={className}>{children}</div>
    </ReasoningContext.Provider>
  )
}

export function ReasoningTrigger({
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  const { isOpen, onOpenChange } = useReasoningContext()
  return (
    <button
      type="button"
      className={cn('flex cursor-pointer items-center gap-2', className)}
      onClick={() => onOpenChange(!isOpen)}
      {...props}
    >
      <span>{children}</span>
      <div className={cn('transform transition-transform', isOpen && 'rotate-180')}>
        <ChevronDownIcon className="size-4" />
      </div>
    </button>
  )
}

export function ReasoningContent({
  children,
  className,
  contentClassName,
  markdown = false,
  ...props
}: {
  children: ReactNode
  className?: string
  contentClassName?: string
  markdown?: boolean
} & HTMLAttributes<HTMLDivElement>) {
  const { isOpen, mounted } = useReasoningContext()
  return (
    <div
      data-state={isOpen ? 'open' : 'closed'}
      className={cn('grid transition-[grid-template-rows] duration-200 ease-out', className)}
      style={{ gridTemplateRows: isOpen ? '1fr' : '0fr' }}
      {...props}
    >
      <div className="overflow-hidden">
        <div className={cn('text-muted-foreground', contentClassName)}>
          {mounted ? (
            markdown ? (
              <ReactMarkdown remarkPlugins={mdRemarkPlugins}>{children as string}</ReactMarkdown>
            ) : (
              children
            )
          ) : null}
        </div>
      </div>
    </div>
  )
}
