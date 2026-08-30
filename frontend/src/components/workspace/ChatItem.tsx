import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface ChatItemProps {
  title: string
  meta?: string
  active?: boolean
  onClick?: () => void
  /** 标题行右侧的悬浮操作（如「···」菜单） */
  action?: ReactNode
  /** 行右缘状态徽标（如 HITL「等待确认」胶囊）：位于相对时间与悬浮操作之间 */
  badge?: ReactNode
  /** 左槽指示器（输出中 loader / 未读圆点）：绝对定位在 24px 左内边距槽内，标题不位移 */
  indicator?: ReactNode
}

/** 会话项：紧凑单行标题、相对时间与悬浮操作。
 *  右缘是单一槽位：默认显示相对时间（或徽标），hover/active 时日期让位给操作按钮
 *  （display 互换——标题 flex-1 吸收宽度，无邻元素位移，故不受「显隐用 opacity」
 *  惯例约束，那是防邻元素跳动的规则）。 */
export function ChatItem({ title, meta, active, onClick, action, badge, indicator }: ChatItemProps) {
  return (
    <div
      className={cn('chat-item', active && 'active', action ? 'has-action' : undefined)}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onClick?.()
      }}
    >
      {indicator && <span className="ci-indicator">{indicator}</span>}
      <span className="t">{title}</span>
      {badge}
      {meta && <span className="m">{meta}</span>}
      {action && <span className="item-action">{action}</span>}
    </div>
  )
}
