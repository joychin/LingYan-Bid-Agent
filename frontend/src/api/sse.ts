/**
 * SSE 订阅封装（@microsoft/fetch-event-source）。
 * 订阅某会话的事件流，按 §5.5 契约把事件回调给上层。
 */

import { fetchEventSource } from '@microsoft/fetch-event-source'
import { getSidecarInfo } from './client'
import type {
  AgentCompleted,
  AgentError,
  AgentReasoning,
  AgentStarted,
  AgentToken,
  ArtifactCreated,
  ConversationRenamed,
  InterruptRequestPayload,
  RunInterrupt,
  RunState as RunStatePayload,
  TodoItemPayload,
  TodoUpdated,
  ToolCalled,
  ToolResult,
} from './events.gen'

// ---- 契约类型单一事实源：sidecar app/contracts/events.py 的 pydantic 模型经
// scripts/gen_ts_types.py 生成 events.gen.ts；本文件只做组合与客户端侧结构（ToolStep）。----

export type TodoStatus = TodoItemPayload['status']
export type TodoItem = TodoItemPayload
export type InterruptRequest = InterruptRequestPayload

/** 工具步骤（运行中由 useRun 维护；run 结束后由 run_traces 快照还原，同构）。 */
export interface ToolStep {
  id: string
  tool: string
  args: Record<string, unknown>
  /** running=执行中；done/error=终态；paused=HITL 中断快照里被门禁拦下、未执行的步骤 */
  status: 'running' | 'done' | 'error' | 'paused'
  summary: string
  error?: string | null
  /** 工具调用 id（tool.called/tool.result 透传；用于精确回填） */
  toolCallId?: string | null
  /** task 步骤：子代理内部 reasoning 增量累积 */
  reasoning: string
  /** 该步骤开始前模型输出的旁白段（narration）：tool.called 封段写入；
   *  历史 trace 由 run_traces 快照还原。旧快照无此键，消费方需防御（?? ''） */
  text?: string
  /** task 步骤：子代理内部工具调用（agent_id 归属） */
  children: ToolStep[]
  /** 计时（ms epoch）：前端事件到达时记 / 历史 trace 用 sidecar 记录的同名字段 */
  startedAt: number
  endedAt?: number | null
}

/**
 * 全部 SSE 事件 payload 的扁平组合（消费侧按事件名取自己那几个字段）。
 * 字段真值在 events.gen.ts（sidecar pydantic 生成）；ping 无 payload 不在此列。
 */
export interface AgentEventData
  extends Partial<
    AgentStarted &
      AgentToken &
      AgentReasoning &
      ToolCalled &
      ToolResult &
      TodoUpdated &
      ArtifactCreated &
      AgentCompleted &
      AgentError &
      RunInterrupt &
      RunStatePayload &
      ConversationRenamed
  > {
  run_id: string
  conversation_id: string
}

export interface SSEHandlers {
  onEvent: (event: string, data: AgentEventData) => void
  onError?: (err: Error) => void
}

/** 同会话同时只允许一条订阅：sidecar 重启窗口内旧连接的自动重连可能与新订阅并存，
 *  两路各投一份事件（卡片/token 双份重影）。新订阅先掐死同会话旧连接。 */
const activeSubs = new Map<string, AbortController>()

/** 订阅会话事件流，返回 AbortController（组件卸载时 abort）。 */
export function subscribeSSE(convId: string, handlers: SSEHandlers): AbortController {
  activeSubs.get(convId)?.abort()
  const ctrl = new AbortController()
  activeSubs.set(convId, ctrl)
  ;(async () => {
    const { baseURL, token } = await getSidecarInfo()
    // React StrictMode 开发模式会「挂载→立刻 abort→重挂载」。abort 若发生在下面的
    // await 期间，fetch-event-source 内部的 addEventListener('abort') 对已取消的
    // 信号永不触发，会留下一条永不关闭的孤儿 SSE 连接——同一事件被两条连接各投递
    // 一次，前端流式文本就会整段翻倍。建立连接前主动检查即可闭合该竞态。
    if (ctrl.signal.aborted) return
    // 重连退避：库默认固定 1s 无限重试——会话被删（永远 404）或 sidecar 长时间不可用时
    // 会形成「每秒重连 + 每次对账触发 messages 重拉」的风暴，拖垮页面交互。
    // 改为指数退避（成功后归零）；404 = 会话不存在，重连无意义，直接终止。
    let retryMs = 1000
    await fetchEventSource(`${baseURL}/api/conversations/${convId}/events`, {
      method: 'GET',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: ctrl.signal,
      onopen: async (res) => {
        if (!res.ok) {
          const err = new Error(`SSE 打开失败: ${res.status}`) as Error & { status?: number }
          err.status = res.status
          throw err
        }
        retryMs = 1000
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
        const status = (err as Error & { status?: number }).status
        if (status === 404) throw err // 会话已删：终止重连（错误经外层 catch 回调）
        handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
        const delay = retryMs
        retryMs = Math.min(retryMs * 2, 15000)
        return delay
      },
    })
  })()
    .catch((err) => {
      // 订阅本身失败（如 getSidecarInfo 拿不到地址、建连失败）也要回调，避免 UI 静默卡在 running
      handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
    })
    .finally(() => {
      if (activeSubs.get(convId) === ctrl) activeSubs.delete(convId)
    })
  return ctrl
}
