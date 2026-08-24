import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode
}

/** 30px 幽灵图标按钮（icon-ghost）：透明底、ink-2，hover 变 panel-2 底 + ink。 */
export function IconButton({ className, children, type = 'button', ...props }: IconButtonProps) {
  return (
    <button type={type} className={cn('icon-ghost', className)} {...props}>
      {children}
    </button>
  )
}
