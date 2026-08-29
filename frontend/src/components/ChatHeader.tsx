import { PanelLeftOpen, PanelRightOpen } from 'lucide-react'
import type { Conversation, Task } from '@/api/client'

/**
 * 中栏顶栏：标题 + 两侧面板「收起后」的展开钮接管位。
 * 开关语义分两半：面板开着时按钮住在面板自己头部（侧栏 side-head 的 PanelLeftClose /
 * 产物面板 ap-head 的 PanelRightClose）；面板收起后按钮由本顶栏接管（左端 PanelLeftOpen /
 * 右端 PanelRightOpen）。两种宿主在同一条 50px 顶栏行、x 位置对齐，观感是
 * 按钮原地换图标、面板从底下滑走。右钮只在产物面板存在（有任务上下文）时渲染；
 * KB 视图不渲染本组件，其侧栏开关常驻 kb-side-head。
 */
export function ChatHeader({
  task,
  conversation,
  sidebarCollapsed,
  onToggleSidebar,
  rightCollapsed,
  onToggleRight,
}: {
  task: Task | null
  conversation: Conversation | null
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  rightCollapsed: boolean
  onToggleRight: () => void
}) {
  return (
    <header className="chat-head" data-tauri-drag-region>
      {sidebarCollapsed && (
        <button type="button" className="head-toggle" title="展开侧栏" onClick={onToggleSidebar}>
          <PanelLeftOpen />
        </button>
      )}
      <div className="chat-head-inner" data-tauri-drag-region>
        {task && <span className="chat-head-task">{task.title}</span>}
        {task && <span className="chat-head-sep">/</span>}
        <span className="chat-head-title">{conversation?.title ?? '新对话'}</span>
      </div>
      {task && rightCollapsed && (
        <button type="button" className="head-toggle" title="展开产物面板" onClick={onToggleRight}>
          <PanelRightOpen />
        </button>
      )}
    </header>
  )
}
