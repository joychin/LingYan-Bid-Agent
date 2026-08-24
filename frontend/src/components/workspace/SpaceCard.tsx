import { useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDown, Folder } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface SpaceCardProps {
  title: string
  icon?: ReactNode
  meta?: ReactNode
  active?: boolean
  defaultOpen?: boolean
  onClick?: () => void
  children?: ReactNode
}

/** 空间卡：标题 + 可选 meta + 可折叠子项（嵌套 nav-item）。 */
export function SpaceCard({ title, icon, meta, active, defaultOpen = true, onClick, children }: SpaceCardProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={cn('space-card', !open && 'collapsed', active && 'active')} onClick={onClick}>
      <div
        className="space-head"
        onClick={(e) => {
          e.stopPropagation()
          setOpen(!open)
        }}
      >
        <div className="space-title">
          {icon ?? <Folder className="folder" />}
          <span className="truncate">{title}</span>
          <ChevronDown className="chev" />
        </div>
        {meta && <div className="space-meta">{meta}</div>}
      </div>
      {children && <div className="space-children">{children}</div>}
    </div>
  )
}
