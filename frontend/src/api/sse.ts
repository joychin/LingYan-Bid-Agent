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

/** 全局同时只允许一条订阅：聊天区一次只显示一个会话，跨会话/同会话都先掐旧再建新。
 *  这是浏览器「每域名 6 条并发连接」预算的结构性防线——SSE 是长连接，旧连接的 abort
 *  经 Vite 代理到上游可能残留半开（页面侧已关、代理/上游侧仍 ESTABLISHED），并发多条
 *  会把连接预算挤爆，后续普通请求（messages 等）永久排队，表现为会话骨架屏永不消失。 */
let activeCtrl: AbortController | null = null

/** 可被 abort 立即打断的退避睡眠（组件卸载/新订阅掐线时不留悬空定时器与监听器）。 */
function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const onAbort = () => {
      clearTimeout(timer)
      resolve()
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

/** 订阅会话事件流，返回 AbortController（组件卸载时 abort）。 */
export function subscribeSSE(convId: string, handlers: SSEHandlers): AbortController {
  activeCtrl?.abort()
  const ctrl = new AbortController()
  activeCtrl = ctrl
  ;(async () => {
    // 重连退避：1s 起指数增长、15s 封顶、建连成功归零。会话被删（永远 404）重连无
    // 意义；退避防的是「sidecar 长时间不可用时每秒重连 + 每次对账触发 messages 重拉」
    // 的风暴拖垮页面交互。
    let retryMs = 1000
    // 自旋重连循环：每轮重新解析 sidecar 地址。Tauri 重启 sidecar 会换端口+token，
    // 建连时的地址快照永久失效——库内重连（onerror 返回延迟）只会复用旧 URL 绕不过
    // 这个缺口，重试节奏必须由本循环掌控。
    while (!ctrl.signal.aborted) {
      try {
        const { baseURL, token } = await getSidecarInfo()
        // React StrictMode 开发模式会「挂载→立刻 abort→重挂载」。abort 若发生在上面的
        // await 期间，fetch-event-source 内部的 addEventListener('abort') 对已取消的
        // 信号永不触发，会留下一条永不关闭的孤儿 SSE 连接——同一事件被两条连接各投递
        // 一次，前端流式文本就会整段翻倍。建连前主动检查即可闭合该竞态。
        if (ctrl.signal.aborted) return
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
          // 一律抛出（不返回重连间隔）：重连节奏与地址重解析由外层循环统一控制
          onerror: (err) => {
            throw err instanceof Error ? err : new Error(String(err))
          },
        })
        // fetchEventSource 正常返回 = 服务端干净结束了响应体（sidecar 重启/优雅关停都
        // 可能走这条路）。不能静默收场——那会让订阅永久死亡（无事件也无报错，流式卡
        // 死到用户切会话）。当作一次断线上报，走重连 + 对账。
        if (!ctrl.signal.aborted) handlers.onError?.(new Error('SSE 连接已被服务端关闭'))
      } catch (err) {
        if (ctrl.signal.aborted) return
        // 404 = 会话已删，重连无意义：回调一次错误后彻底终止
        handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
        if ((err as Error & { status?: number }).status === 404) return
      }
      await sleep(retryMs, ctrl.signal)
      retryMs = Math.min(retryMs * 2, 15000)
    }
  })().finally(() => {
    if (activeCtrl === ctrl) activeCtrl = null
  })
  return ctrl
}
