import { useEffect, useState } from 'react'
import { Check, ChevronDown, Image as ImageIcon, Settings2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface ModelOption {
  id: string
  name: string
  model: string
  imageSupport: boolean
}

/** 输入框底栏的「模型」选择胶囊（与任务/思考胶囊同语言）。
 *  列出全部已配置模型，选中随每条消息发送（多模型 profile）；
 *  尾项「管理模型…」进设置。选中状态由 ChatView 持有（按会话粘性）。 */
export function ModelSelect({
  options,
  value,
  onChange,
  onManage,
}: {
  options: ModelOption[]
  value: string
  onChange: (id: string) => void
  onManage: () => void
}) {
  const [open, setOpen] = useState(false)
  const current = options.find((o) => o.id === value)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: PointerEvent) => {
      const t = e.target as HTMLElement | null
      if (t && !t.closest('[data-model-select]')) setOpen(false)
    }
    document.addEventListener('pointerdown', onDoc)
    return () => document.removeEventListener('pointerdown', onDoc)
  }, [open])

  return (
    <div
      className="relative"
      data-model-select
      onKeyDown={(e) => {
        if (e.key === 'Escape') setOpen(false)
      }}
    >
      <button
        type="button"
        className="flex items-center gap-0.5 rounded px-1 py-0.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
        onClick={() => setOpen(!open)}
        title="选择模型：随每条消息生效"
      >
        <span className="max-w-[120px] truncate" title={current?.name}>
          {current?.name ?? '模型'}
        </span>
        <ChevronDown className={cn('h-3 w-3 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute bottom-full right-0 z-30 mb-2 w-52 rounded-[var(--radius)] border border-line bg-card py-1.5 shadow-[0_-2px_8px_rgba(16,24,40,0.04),0_8px_18px_rgba(16,24,40,0.1)]">
          <p className="px-2.5 pb-1 pt-0.5 text-[11px] text-muted-foreground">模型（对下一条消息生效）</p>
          {options.length === 0 && (
            <p className="px-2.5 py-1.5 text-xs text-muted-foreground">还没有配置模型</p>
          )}
          {options.map((o) => (
            <button
              key={o.id}
              type="button"
              onClick={() => {
                onChange(o.id)
                setOpen(false)
              }}
              className={cn(
                'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm',
                o.id === value ? 'bg-accent-soft' : 'hover:bg-secondary',
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1">
                  <span className="truncate">{o.name}</span>
                  {o.imageSupport && (
                    <ImageIcon className="h-3 w-3 shrink-0 text-muted-foreground" aria-label="支持图片" />
                  )}
                </span>
                <span className="block truncate font-mono text-xs text-muted-foreground">{o.model}</span>
              </span>
              {o.id === value && <Check className="h-4 w-4 shrink-0 text-primary" />}
            </button>
          ))}
          <div className="my-1 border-t border-line" />
          <button
            type="button"
            onClick={() => {
              setOpen(false)
              onManage()
            }}
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm text-muted-foreground hover:bg-secondary"
          >
            <Settings2 className="h-3.5 w-3.5" />
            管理模型…
          </button>
        </div>
      )}
    </div>
  )
}
