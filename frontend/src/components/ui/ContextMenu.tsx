import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

export interface ContextMenuItem {
  label: string
  action?: () => void
  disabled?: boolean
  danger?: boolean
}

/**
 * 通用右键菜单浮层（从目录树编辑器 TreeContextMenu 的壳抽出）：
 * fixed 定位 + 右缘/底缘回退（挂载测量后修正，绝不溢出视口）、Escape/外点关闭。
 * Escape 在捕获段拦截并阻断——宿主另有 Esc 语义（如工作区编辑器收起）时互不误触。
 */
export function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number
  y: number
  items: ContextMenuItem[]
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: x, top: y })

  // 浮层纪律：右缘/底缘越界则回退，绝不溢出视口
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setPos({
      left: Math.min(x, window.innerWidth - r.width - 8),
      top: Math.min(y, window.innerHeight - r.height - 8),
    })
  }, [x, y])

  useEffect(() => {
    const close = () => onClose()
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      onClose()
    }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [onClose])

  if (items.length === 0) return null

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-44 rounded-lg border border-line bg-card py-1 shadow-lg"
      style={pos}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((it) => (
        <button
          key={it.label}
          type="button"
          disabled={it.disabled}
          onClick={() => {
            it.action?.()
            onClose()
          }}
          className={cn(
            'flex w-full items-center px-3 py-1.5 text-left text-xs',
            it.disabled
              ? 'cursor-default text-muted-foreground/50'
              : it.danger
                ? 'text-destructive hover:bg-destructive/10'
                : 'text-foreground hover:bg-muted',
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}
