import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface ChatItemProps {
  title: string
  meta?: string
  active?: boolean
  onClick?: () => void
  /** 标题行右侧的悬浮操作（如「···」菜单） */
  action?: ReactNode
}

/** 会话项：紧凑单行标题、相对时间与悬浮操作。 */
export function ChatItem({ title, meta, active, onClick, action }: ChatItemProps) {
  return (
    <div
      className={cn('chat-item', active && 'active')}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onClick?.()
      }}
    >
      <span className="t">{title}</span>
      {meta && <span className="m">{meta}</span>}
      {action && <span className="item-action">{action}</span>}
    </div>
  )
}
