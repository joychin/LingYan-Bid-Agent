/**
 * SSE 订阅封装（@microsoft/fetch-event-source）。
 * 订阅某会话的事件流，按 §5.5 契约把事件回调给上层。
 */

import { fetchEventSource } from '@microsoft/fetch-event-source'
import { getSidecarInfo } from './client'

export interface AgentEventData {
  run_id: string
  conversation_id: string
  text?: string
  tool?: string
  args?: Record<string, unknown>
  summary?: string
  message_id?: string
  error?: string
}

export interface SSEHandlers {
  onEvent: (event: string, data: AgentEventData) => void
  onError?: (err: Error) => void
}

/** 订阅会话事件流，返回 AbortController（组件卸载时 abort）。 */
export function subscribeSSE(convId: string, handlers: SSEHandlers): AbortController {
  const ctrl = new AbortController()
  ;(async () => {
    const { baseURL, token } = await getSidecarInfo()
    // React StrictMode 开发模式会「挂载→立刻 abort→重挂载」。abort 若发生在下面的
    // await 期间，fetch-event-source 内部的 addEventListener('abort') 对已取消的
    // 信号永不触发，会留下一条永不关闭的孤儿 SSE 连接——同一事件被两条连接各投递
    // 一次，前端流式文本就会整段翻倍。建立连接前主动检查即可闭合该竞态。
    if (ctrl.signal.aborted) return
    await fetchEventSource(`${baseURL}/api/conversations/${convId}/events`, {
      method: 'GET',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: ctrl.signal,
      onopen: async (res) => {
        if (!res.ok) throw new Error(`SSE 打开失败: ${res.status}`)
      },
      onmessage: (msg) => {
        if (!msg.event || msg.event === 'ping') return
        try {
          handlers.onEvent(msg.event, JSON.parse(msg.data) as AgentEventData)
        } catch {
          /* 忽略解析失败的数据 */
        }
      },
      onerror: (err) => {
        handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
        // 不抛异常：fetch-event-source 会自动重连（MVP 不做 Last-Event-ID）
      },
    })
  })().catch((err) => {
    // 订阅本身失败（如 getSidecarInfo 拿不到地址、建连失败）也要回调，避免 UI 静默卡在 running
    handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
  })
  return ctrl
}
