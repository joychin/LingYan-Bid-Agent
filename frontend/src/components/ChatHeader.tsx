import { Plus } from 'lucide-react'
import type { Conversation, Task } from '@/api/client'

/**
 * 中栏顶栏：任务名/会话标题 + 「＋ 新会话」。自动命名经 conversation.renamed →
 * conversations 缓存失效即时刷新。新会话按钮只在有任务时出现（未归类旧会话无处派生），
 * 语义与侧栏任务 hover「＋」同款：在当前任务内建会话并进入——「任务即房间」，
 * 会话永远从任务内诞生，不再有跨任务的「新建会话」入口。
 * 左右面板开关不在这里——它们是钉在窗口顶角的固定按钮（App 渲染，.head-toggle.pin-*），
 * 位置不随面板开合变化，顶栏只在侧栏/右面板收起时让出对应角落的点击区。
 */
export function ChatHeader({
  task,
  conversation,
  onNewConversation,
}: {
  task: Task | null
  conversation: Conversation | null
  /** 在当前任务内新建会话并进入（App 接线；无任务时不渲染按钮） */
  onNewConversation?: () => void
}) {
  return (
    <header className="chat-head" data-tauri-drag-region>
      <div className="chat-head-inner" data-tauri-drag-region>
        {task && <span className="chat-head-task">{task.title}</span>}
        {task && <span className="chat-head-sep">/</span>}
        <span className="chat-head-title">{conversation?.title ?? '新对话'}</span>
        {task && onNewConversation && (
          <button
            type="button"
            className="chat-head-new"
            title="在当前任务新建会话"
            onClick={onNewConversation}
          >
            <Plus />
            新会话
          </button>
        )}
      </div>
    </header>
  )
}
