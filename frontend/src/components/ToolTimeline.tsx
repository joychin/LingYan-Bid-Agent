import { useState } from 'react'
import { CheckCircle2, ChevronDown, ChevronRight, Loader2, Wrench } from 'lucide-react'
import type { ToolStep } from '@/hooks/useRun'
import { cn } from '@/lib/utils'

/** 当前 run 的工具调用时间线（spinner → ✓，可折叠看 summary）。 */
export function ToolTimeline({ tools }: { tools: ToolStep[] }) {
  const [collapsed, setCollapsed] = useState(false)
  if (tools.length === 0) return null

  return (
    <div className="flex w-full justify-start">
      <div className="w-full max-w-[85%] rounded-lg border bg-muted/40 text-sm">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted-foreground hover:text-foreground"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          <Wrench className="h-4 w-4" />
          工具调用（{tools.filter((t) => t.status === 'done').length}/{tools.length}）
        </button>
        {!collapsed && (
          <ul className="space-y-1.5 border-t px-3 py-2">
            {tools.map((t) => (
              <li key={t.id} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  {t.status === 'running' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                  ) : (
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                  )}
                  <code className="font-mono text-xs">{t.tool}</code>
                  <span className="truncate text-xs text-muted-foreground">
                    {JSON.stringify(t.args)?.slice(0, 120)}
                  </span>
                </div>
                {t.status === 'done' && t.summary && (
                  <p className={cn('pl-5 text-xs text-muted-foreground')}>{t.summary}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
