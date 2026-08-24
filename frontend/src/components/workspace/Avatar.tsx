import { cn } from '@/lib/utils'

export interface AvatarProps {
  name: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

/** 首字圆形头像：sm=24、md=28（用户栏/侧栏默认）、lg=32（消息头）。 */
export function Avatar({ name, size = 'md', className }: AvatarProps) {
  return (
    <span className={cn('avatar', size === 'sm' && 'avatar-sm', size === 'lg' && 'avatar-lg', className)}>
      {name.charAt(0) || '?'}
    </span>
  )
}
