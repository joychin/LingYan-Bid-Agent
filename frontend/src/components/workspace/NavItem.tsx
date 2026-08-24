import { Folder } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface NavItemProps {
  title: string
  meta?: string
  folder?: boolean
  active?: boolean
  onClick?: () => void
}

/** 任务树叶子项：可选文件夹图标 + 标题 + meta；active 为白卡 + 阴影。 */
export function NavItem({ title, meta, folder = false, active, onClick }: NavItemProps) {
  return (
    <div
      className={cn('nav-item', active && 'active')}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onClick?.()
      }}
    >
      <div className="title-row">
        {folder && <Folder className="folder" />}
        <span className="truncate">{title}</span>
      </div>
      {meta && (
        <div className="meta">
          <span>{meta}</span>
        </div>
      )}
    </div>
  )
}
