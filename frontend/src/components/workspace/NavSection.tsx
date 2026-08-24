import { useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface NavSectionProps {
  title: string
  count?: number
  defaultOpen?: boolean
  children?: ReactNode
}

/** 可折叠导航区块：标题 + 计数（渲染为「标题（计数）」）+ chevron，折叠时隐藏子项。 */
export function NavSection({ title, count, defaultOpen = true, children }: NavSectionProps) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={cn('nav-section', !open && 'collapsed')}>
      <div className="nav-section-title" onClick={() => setOpen(!open)}>
        <span>
          {title}
          {typeof count === 'number' && (
            <>
              （<span className="count">{count}</span>）
            </>
          )}
        </span>
        <ChevronDown className="chev" />
      </div>
      {children}
    </div>
  )
}
