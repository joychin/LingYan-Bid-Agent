import { useState } from 'react'
import { CheckCircle, ChevronDown, Loader2, Settings, XCircle } from 'lucide-react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

/** prompt-kit Tool 移植：可折叠工具调用卡片（状态图标 + badge + input/output/error 详情）。 */
export type ToolPart = {
  type: string
  state:
    | 'input-streaming'
    | 'input-available'
    | 'output-available'
    | 'output-error'
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  toolCallId?: string
  errorText?: string
}

export function Tool({
  toolPart,
  defaultOpen = false,
  className,
}: {
  toolPart: ToolPart
  defaultOpen?: boolean
  className?: string
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  const { state, input, output, toolCallId } = toolPart

  const stateIcon = (() => {
    switch (state) {
      case 'input-streaming':
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
      case 'input-available':
        return <Settings className="h-4 w-4 text-orange-500" />
      case 'output-available':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'output-error':
        return <XCircle className="h-4 w-4 text-red-500" />
      default:
        return <Settings className="h-4 w-4 text-muted-foreground" />
    }
  })()

  const badge = (() => {
    const base = 'rounded-full px-2 py-1 text-xs font-medium'
    switch (state) {
      case 'input-streaming':
        return <span className={cn(base, 'bg-blue-100 text-blue-700')}>Processing</span>
      case 'input-available':
        return <span className={cn(base, 'bg-orange-100 text-orange-700')}>Ready</span>
      case 'output-available':
        return <span className={cn(base, 'bg-green-100 text-green-700')}>Completed</span>
      case 'output-error':
        return <span className={cn(base, 'bg-red-100 text-red-700')}>Error</span>
      default:
        return <span className={cn(base, 'bg-muted text-muted-foreground')}>Pending</span>
    }
  })()

  const formatValue = (value: unknown): string => {
    if (value === null) return 'null'
    if (value === undefined) return 'undefined'
    if (typeof value === 'string') return value
    if (typeof value === 'object') return JSON.stringify(value, null, 2)
    return String(value)
  }

  return (
    <div className={cn('mt-3 overflow-hidden rounded-lg border border-border', className)}>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger className="flex h-auto w-full items-center justify-between gap-2 rounded-none bg-background px-3 py-2 text-left text-sm font-normal hover:bg-accent">
          <div className="flex items-center gap-2">
            {stateIcon}
            <span className="font-mono text-sm font-medium">{toolPart.type}</span>
            {badge}
          </div>
          <ChevronDown className={cn('h-4 w-4 transition-transform', isOpen && 'rotate-180')} />
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t border-border">
          <div className="space-y-3 bg-background p-3">
            {input && Object.keys(input).length > 0 && (
              <div>
                <h4 className="mb-2 text-sm font-medium text-muted-foreground">Input</h4>
                <div className="rounded border bg-background p-2 font-mono text-sm">
                  {Object.entries(input).map(([key, value]) => (
                    <div key={key} className="mb-1">
                      <span className="text-muted-foreground">{key}:</span> <span>{formatValue(value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {output && (
              <div>
                <h4 className="mb-2 text-sm font-medium text-muted-foreground">Output</h4>
                <div className="max-h-60 overflow-auto rounded border bg-background p-2 font-mono text-sm">
                  <pre className="whitespace-pre-wrap">{formatValue(output)}</pre>
                </div>
              </div>
            )}
            {state === 'output-error' && toolPart.errorText && (
              <div>
                <h4 className="mb-2 text-sm font-medium text-red-500">Error</h4>
                <div className="rounded border border-red-200 bg-background p-2 text-sm">{toolPart.errorText}</div>
              </div>
            )}
            {state === 'input-streaming' && (
              <div className="text-sm text-muted-foreground">Processing tool call...</div>
            )}
            {toolCallId && (
              <div className="border-t pt-2 text-xs text-muted-foreground">
                <span className="font-mono">Call ID: {toolCallId}</span>
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
