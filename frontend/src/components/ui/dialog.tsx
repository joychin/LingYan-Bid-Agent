import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}

/** 轻量模态弹窗（shadcn Dialog 风格，未引入 radix）。 */
export function Dialog({ open, onClose, title, children }: DialogProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <div
        className={cn(
          'relative z-10 w-full max-w-md rounded-2xl border bg-card p-6 shadow-lg',
          'max-h-[85vh] overflow-y-auto',
        )}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
