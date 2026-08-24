import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface NavRowProps {
  icon: ReactNode
  label: string
  hint?: string
  active?: boolean
  onClick?: () => void
}

/** 快捷导航行：图标 + 文字 + 右侧提示；active 为白卡 + 阴影，图标着 accent。 */
export function NavRow({ icon, label, hint, active, onClick }: NavRowProps) {
  return (
    <div
      className={cn('nav-row', active && 'active')}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onClick?.()
      }}
    >
      <span className="icon">{icon}</span>
      <span className="txt">{label}</span>
      {hint && <span className="row-hint">{hint}</span>}
    </div>
  )
}
