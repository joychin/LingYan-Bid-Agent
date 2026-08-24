import type { ReactNode } from 'react'

export interface MessageProps {
  role: 'user' | 'assistant'
  /** assistant 名（如 "Hy3"） */
  name?: string
  avatar?: ReactNode
  /** assistant 状态胶囊（如「已完成 · 3 个步骤」） */
  status?: ReactNode
  time?: string
  children?: ReactNode
}

/** 消息容器：user 右对齐气泡（右上角小圆角）；assistant 头像 + 名字/状态头 + 内容。 */
export function Message({ role, name, avatar, status, time, children }: MessageProps) {
  if (role === 'user') {
    return (
      <div className="msg user">
        <div className="msg-body">
          <div className="bubble">{children}</div>
        </div>
      </div>
    )
  }
  return (
    <div className="msg assistant">
      {avatar ?? <div className="msg-avatar">H</div>}
      <div className="msg-body">
        <div className="msg-head">
          {name && <span className="msg-name">{name}</span>}
          {time && <span className="msg-time">{time}</span>}
          {status && <span className="msg-status">{status}</span>}
        </div>
        {children}
      </div>
    </div>
  )
}
