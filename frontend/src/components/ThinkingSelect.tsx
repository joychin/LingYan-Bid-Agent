import { useEffect, useState } from 'react'
import { Brain, Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ThinkingLevel } from '@/api/client'

const LEVELS: { value: ThinkingLevel; label: string; hint: string }[] = [
  { value: 'low', label: '低', hint: '轻量思考，响应更快' },
  { value: 'medium', label: '中', hint: '均衡的思考深度' },
  { value: 'high', label: '高', hint: '深度思考，适合复杂问题' },
]

/** 输入框底栏的「思考强度」选择胶囊（与任务/模型胶囊同语言）。
 *  档位随每条消息发送（reasoning_effort），对下一条消息生效；
 *  选中状态由 ChatView 持有并持久化到 localStorage。 */
export function ThinkingSelect({
  value,
  onChange,
}: {
  value: ThinkingLevel
  onChange: (level: ThinkingLevel) => void
}) {
  const [open, setOpen] = useState(false)
  const current = LEVELS.find((l) => l.value === value) ?? LEVELS[0]

  useEffect(() => {
    if (!open) return
    const onDoc = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null
      if (t && !t.closest('[data-thinking-select]')) setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [open])

  return (
    <div
      className="relative"
      data-thinking-select
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
    >
      <button
        type="button"
        className="flex items-center gap-1 rounded px-1.5 py-1 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
        onClick={() => setOpen(!open)}
        title="思考强度：随每条消息生效"
      >
        <Brain className="h-4 w-4 text-muted-foreground" />
        <span>{current.label}</span>
        <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute bottom-full right-0 z-30 mb-2 w-56 rounded-[var(--Radius-radius-12)] border border-line bg-card py-1.5 shadow-md">
          <p className="px-2.5 pb-1 pt-0.5 text-[11px] text-muted-foreground">思考强度（随每条消息生效）</p>
          {LEVELS.map((l) => (
            <button
              key={l.value}
              type="button"
              onClick={() => {
                onChange(l.value)
                setOpen(false)
              }}
              className={cn(
                'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm',
                l.value === value ? 'bg-accent-soft' : 'hover:bg-secondary',
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="block">{l.label}</span>
                <span className="block text-xs text-muted-foreground">{l.hint}</span>
              </span>
              {l.value === value && <Check className="h-4 w-4 shrink-0 text-primary" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
