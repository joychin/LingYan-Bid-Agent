import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface NavRowProps {
  icon: ReactNode
  label: string
  hint?: string
  active?: boolean
  /** 右侧红点（有待处理事项提醒，如知识库待确认条目） */
  badge?: boolean
  onClick?: () => void
}

/** 快捷导航行：图标 + 文字 + 右侧提示/红点；active 为白卡 + 阴影，图标着 accent。 */
export function NavRow({ icon, label, hint, active, badge, onClick }: NavRowProps) {
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
      {badge && <span className="nav-badge" aria-label="有待确认内容" />}
    </div>
  )
}
