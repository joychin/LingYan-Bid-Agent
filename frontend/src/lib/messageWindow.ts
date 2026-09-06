import type { Message } from '@/api/client'
import { isRespondAnswer } from '@/lib/hitlMessage'

/**
 * 长会话首屏只渲染最近一个窗口（切换会话的冷挂载成本从全量降到尾部），向上
 * 翻阅时「加载更早」逐步扩窗。起点必须对齐到回合头：窗口首条是 user 消息且
 * 不是 HITL 回答消息——MessageList 的回答隐藏/回合分组（isRespondAnswer 依赖
 * 前一条消息）在窗口边界才不会错位（窗口头即回合头，整回合完整在窗内）。
 * 返回 0 = 全量（消息不足一窗，或对齐一路回退到开头）。
 */
export function computeWindowStart(messages: Message[], windowSize: number): number {
  if (messages.length <= windowSize) return 0
  let start = messages.length - windowSize
  while (start > 0) {
    if (messages[start].role === 'user' && !isRespondAnswer(messages, start)) break
    start--
  }
  return start
}
