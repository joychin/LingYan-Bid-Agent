import type { Conversation, Task } from '@/api/client'

/** 中栏顶栏：任务名 / 会话标题。自动命名经 conversation.renamed → conversations
 *  缓存失效即时刷新；草稿页（无会话）显示「新对话」。 */
export function ChatHeader({ task, conversation }: { task: Task | null; conversation: Conversation | null }) {
  return (
    <header className="chat-head" data-tauri-drag-region>
      <div className="chat-head-inner" data-tauri-drag-region>
        {task && <span className="chat-head-task">{task.title}</span>}
        {task && <span className="chat-head-sep">/</span>}
        <span className="chat-head-title">{conversation?.title ?? '新对话'}</span>
      </div>
    </header>
  )
}
