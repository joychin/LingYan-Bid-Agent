import type { ReactNode } from 'react'
import { Avatar } from './Avatar'

export interface UserBarProps {
  name: string
  avatar?: ReactNode
  actions?: ReactNode
}

/** 侧栏底部用户栏：头像 + 名字 + 右侧操作（设置等）。 */
export function UserBar({ name, avatar, actions }: UserBarProps) {
  return (
    <div className="user-bar">
      {avatar ?? <Avatar name={name} />}
      <span className="name truncate">{name}</span>
      <div className="user-actions">{actions}</div>
    </div>
  )
}
