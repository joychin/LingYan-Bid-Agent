import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getLatestRun, resumeRun, cancelRun, sendMessage, type HitlDecision } from '@/api/client'
import { subscribeSSE, type InterruptRequest, type TodoItem, type ToolStep } from '@/api/sse'
import { useSidecarHealth } from '@/context/SidecarHealth'

export type { ToolStep }

export interface RunState {
  running: boolean
  /** 已请求停止、等待事件边界收尾（agent.error 到达前）：停止钮转「正在停止…」防重复点 */
  stopping: boolean
  /** 当前 run id：停止按钮（POST /runs/{rid}/cancel）与 SSE 事件对账用 */
  runId: string | null
  /** run 开始时间（ms epoch）：驱动「执行中 · 12s」总计时 */
  startedAt: number | null
  streamText: string
  reasoningText: string
  tools: ToolStep[]
  todos: TodoItem[]
  done: number
  total: number
  error: string | null
  /** 最近一次发送的文本：发送失败重试用（此时用户消息可能未落库，不能从消息列表取） */
  lastSent: string
  /** HITL 暂停（run.interrupt / run.state 对账）：非空 = 有待用户裁决的动作，输入框切回答模式 */
  interrupt: { runId: string; requests: InterruptRequest[] } | null
}

const INITIAL_STATE: RunState = {
  running: false,
  stopping: false,
  runId: null,
  startedAt: null,
  streamText: '',
  reasoningText: '',
  tools: [],
  todos: [],
  done: 0,
  total: 0,
  error: null,
  lastSent: '',
  interrupt: null,
}

/** 收敛已结束的 run：只有处于 running 态时才动作，避免历史 run 的 run.state 反复打扰 */
function convergeRun(s: RunState, error: string | null): RunState {
  if (!s.running) return s
  return { ...INITIAL_STATE, lastSent: s.lastSent, error }
}

function newStep(id: string, data: { tool?: string; args?: Record<string, unknown>; tool_call_id?: string | null }): ToolStep {
  return {
    id,
    tool: data.tool ?? 'unknown',
    args: data.args ?? {},
    status: 'running',
    summary: '',
    error: null,
    toolCallId: data.tool_call_id ?? null,
    reasoning: '',
    text: '',
    children: [],
    startedAt: Date.now(),
    endedAt: null,
  }
}

/** 不可变地把新步骤挂进树：带 agent_id 挂对应 task 的 children，否则挂顶层。 */
function attachStep(steps: ToolStep[], step: ToolStep, agentId?: string | null): ToolStep[] {
  if (agentId) {
    return steps.map((s) => {
      if (s.tool === 'task' && s.toolCallId === agentId) return { ...s, children: [...s.children, step] }
      if (s.children.length > 0) {
        const children = attachStep(s.children, step, agentId)
        if (children !== s.children) return { ...s, children }
      }
      return s
    })
  }
  return [...steps, step]
}

/** 不可变回填：按 tool_call_id（缺省退化按工具名）找 running 步骤写终态。 */
function fillStep(steps: ToolStep[], data: { tool?: string; tool_call_id?: string | null; summary?: string; error?: string }): ToolStep[] {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]
    if (s.status === 'running') {
      const tcid = data.tool_call_id ?? null
      const match = tcid ? s.toolCallId === tcid : s.tool === data.tool
      if (match) {
        const isError = !!data.error
        return [
          ...steps.slice(0, i),
          {
            ...s,
            status: isError ? 'error' : 'done',
            summary: data.summary ?? '',
            error: data.error,
            endedAt: Date.now(),
          },
          ...steps.slice(i + 1),
        ]
      }
    }
    if (s.children.length > 0) {
      const children = fillStep(s.children, data)
      if (children !== s.children) {
        return [...steps.slice(0, i), { ...s, children }, ...steps.slice(i + 1)]
      }
    }
  }
  return steps
}

/** 树里是否已有该 tool_call_id（双连接重影的最后防线：同调用只入树一次）。 */
function hasStepByCallId(steps: ToolStep[], toolCallId: string): boolean {
  return steps.some(
    (s) => s.toolCallId === toolCallId || (s.children.length > 0 && hasStepByCallId(s.children, toolCallId)),
  )
}

/** 把子代理 reasoning 增量累积到所属 task 步骤（不可变）。 */
function appendReasoning(steps: ToolStep[], agentId: string, text: string): ToolStep[] {
  return steps.map((s) => {
    if (s.tool === 'task' && s.toolCallId === agentId) return { ...s, reasoning: s.reasoning + text }
    if (s.children.length > 0) {
      const children = appendReasoning(s.children, agentId, text)
      if (children !== s.children) return { ...s, children }
    }
    return s
  })
}

/** 订阅会话事件流并驱动一个正在进行的 run（agent.started -> token… -> completed）。 */
export function useRun(convId: string | null) {
  const queryClient = useQueryClient()
  const { reconnectSeq } = useSidecarHealth()
  const [state, setState] = useState<RunState>(INITIAL_STATE)
  const seqRef = useRef(0)
  // 已通过 SSE 收到终态的 run：HTTP 对账（断线期间）拿到的过期 running 状态不再复活它
  const terminalRunsRef = useRef<Set<string>>(new Set())
  const lastReconcileRef = useRef(0)
  // seq 去重：记录当前 run 已接受的最高序列号（run 切换时随 seq=1 重置）
  const lastSeqRef = useRef<{ runId: string; seq: number } | null>(null)

  useEffect(() => {
    if (!convId) return
    seqRef.current = 0
    terminalRunsRef.current = new Set()
    lastReconcileRef.current = 0
    setState(INITIAL_STATE)
    const ctrl = subscribeSSE(convId, {
      onEvent: (event, data) => {
        if (data.conversation_id !== convId) return
        // seq 去重（契约 additive 扩展）：双连接残留的重复投递直接丢弃（结构上终结重影）；
        // 缺口告警不重放（MVP 断线策略仍是重拉 messages）。无 seq（旧 sidecar）照常接受。
        if (typeof data.seq === 'number') {
          const last = lastSeqRef.current
          if (last && last.runId === data.run_id) {
            if (data.seq <= last.seq) return
            if (data.seq > last.seq + 1) {
              console.warn(`[sse] 事件缺口：期望 ${last.seq + 1}，收到 ${data.seq}（run ${data.run_id}）`)
            }
          }
          lastSeqRef.current = { runId: data.run_id, seq: data.seq }
        }
        switch (event) {
          case 'agent.started':
            setState((s) => ({
              ...INITIAL_STATE,
              running: true,
              runId: data.run_id,
              startedAt: Date.now(),
              lastSent: s.lastSent,
            }))
            break
          case 'agent.token':
            setState((s) => ({ ...s, streamText: s.streamText + (data.text ?? '') }))
            break
          case 'agent.reasoning':
            // 推理模型的 chain-of-thought 增量；agent_id 非空时归属子代理（累积到 task 步骤）
            if (data.agent_id) {
              setState((s) => ({ ...s, tools: appendReasoning(s.tools, data.agent_id!, data.text ?? '') }))
            } else {
              setState((s) => ({ ...s, reasoningText: s.reasoningText + (data.text ?? '') }))
            }
            break
          case 'tool.called': {
            const id = `${Date.now()}-${seqRef.current++}`
            setState((s) => {
              // 幂等兜底：双连接窗口内同一调用可能投递两次（单飞订阅已基本防住）
              const callId = data.tool_call_id ?? null
              if (callId && hasStepByCallId(s.tools, callId)) return s
              const step = newStep(id, data)
              if (!data.agent_id) {
                // 主 agent 调用：把之前流出的正文封为旁白挂到本步骤（与 sidecar 同一条
                // 封段规则，SSE 契约零改动）；正文气泡只剩最终回复（最后未封口段）。
                // 子代理调用不封段（其正文 token 本就不透传，streamText 恒为空）
                step.text = s.streamText
                return { ...s, tools: attachStep(s.tools, step, data.agent_id), streamText: '' }
              }
              return { ...s, tools: attachStep(s.tools, step, data.agent_id) }
            })
            break
          }
          case 'tool.result':
            setState((s) => ({ ...s, tools: fillStep(s.tools, data) }))
            break
          case 'todo.updated':
            setState((s) => ({ ...s, todos: data.items ?? [], done: data.done ?? 0, total: data.total ?? 0 }))
            break
          case 'artifact.created':
            // 产物已落库，刷新列表让 ArtifactCard 即时出现
            void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
            break
          case 'conversation.renamed':
            // 自动命名已写库（无 seq 连接级事件），刷新会话列表让侧栏标题即时更新
            void queryClient.invalidateQueries({ queryKey: ['conversations'] })
            break
          case 'run.state': {
            // 连接建立时的对账（sidecar 不补发历史事件）：
            // 在跑则恢复 running（重连/新挂载错过 agent.started），已结束则收敛
            if (data.status === 'running') {
              if (!terminalRunsRef.current.has(data.run_id)) {
                // 恢复 running 态：计时从恢复时刻重新起算（拿不到真实起点，近似）
                setState((s) => ({
                  ...s,
                  running: true,
                  runId: s.runId ?? data.run_id,
                  error: null,
                  startedAt: s.startedAt ?? Date.now(),
                }))
              }
            } else if (data.status === 'waiting_input') {
              // HITL 对账：恢复审批/问答卡。半截回复已由 sidecar 落库，
              // 拉回消息并清掉流式气泡，避免与落库消息双显
              if (!terminalRunsRef.current.has(data.run_id)) {
                setState((s) => ({
                  ...s,
                  running: false,
                  stopping: false,
                  streamText: '',
                  reasoningText: '',
                  interrupt: { runId: data.run_id, requests: data.requests ?? [] },
                }))
                void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
              }
            } else {
              const err = data.status === 'error' ? (data.error ?? '任务已中断') : null
              setState((s) => convergeRun(s, err))
              // 收敛时拉真值（run 已结束但客户端错过了 completed/error 事件）
              void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
            }
            break
          }
          case 'run.interrupt':
            // HITL 暂停（additive）：run 转 waiting_input。与 completed 同款时序——
            // 先拉回落库的半截消息（带「等待你的输入…」标记与 trace）再清流式气泡
            void queryClient
              .invalidateQueries({ queryKey: ['messages', convId] })
              .then(() =>
                setState((s) => ({
                  ...s,
                  running: false,
                  stopping: false,
                  streamText: '',
                  reasoningText: '',
                  interrupt: { runId: data.run_id, requests: data.requests ?? [] },
                })),
              )
            break
          case 'agent.completed':
            terminalRunsRef.current.add(data.run_id)
            // 等落库消息拉回后再撤掉流式气泡：避免「清空->闪空->再出现」，
            // 流式累积文本与落库内容一致，替换是无缝的
            void queryClient
              .invalidateQueries({ queryKey: ['messages', convId] })
              .then(() =>
                setState((s) => ({
                  ...s,
                  running: false,
                  stopping: false,
                  streamText: '',
                  reasoningText: '',
                  error: null,
                  interrupt: null,
                })),
              )
            break
            case 'agent.error':
              terminalRunsRef.current.add(data.run_id)
              // sidecar 已把中断 run 的半截回复落库（带「（任务中断）」标记）：拉回消息让
              // UI 与模型记忆对齐；清空流式气泡避免与落库消息双显（同 completed 的时序）
              void queryClient
                .invalidateQueries({ queryKey: ['messages', convId] })
                .then(() =>
                  setState((s) => ({
                    ...s,
                    running: false,
                    stopping: false,
                    streamText: '',
                    reasoningText: '',
                    error: data.error ?? '未知错误',
                    interrupt: null,
                  })),
                )
              break
        }
      },
      onError: () => {
        // 连接失败 ≠ 任务失败：不能把 running 置 false--重连后没有 agent.started 补发，
        // 流式 UI 会永久丢失且用户可再发消息（后端 409）。fetch-event-source 会自动重连，
        // 恢复由连接建立时的 run.state 对账事件完成；sidecar 存活状态由 SidecarBanner 呈现。
        // 这里只做限频的 best-effort 对账：查最新 run，确认已结束才收敛（sidecar 重启等场景）。
        if (Date.now() - lastReconcileRef.current < 2000) return
        lastReconcileRef.current = Date.now()
        getLatestRun(convId)
          .then(({ run }) => {
            if (run && (run.status === 'running' || run.status === 'waiting_input')) {
              // 任务仍在执行或等待用户输入：保持现状等事件（waiting_input 由 run.state 对账恢复卡）
              return
            }
            const err = run && run.status === 'error' ? (run.error ?? '任务已中断') : null
            setState((s) => convergeRun(s, err))
            void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
          })
          .catch(() => {
            /* sidecar 暂不可达：保持现状，等重连或健康探活恢复 */
          })
      },
    })
    return () => ctrl.abort()
    // reconnectSeq 递增（sidecar 恢复/换端口）时重挂流
  }, [convId, queryClient, reconnectSeq])

  const send = useCallback(
    async (text: string) => {
      if (!convId) return
      const content = text.trim()
      if (!content) return
      // HITL 等待中：输入框的回答 = respond 决策（代替工具执行，回答合成为工具结果续跑）
      if (state.interrupt) {
        const runId = state.interrupt.runId
        setState((s) => ({ ...s, lastSent: content }))
        try {
          await resumeRun(runId, [{ type: 'respond', message: content }])
          // 乐观置 running（真正的 agent.started 随后到达并做同样的事），
          // 封住「202 到 started 之间」的发送窗口
          setState((s) => ({ ...INITIAL_STATE, running: true, runId, startedAt: Date.now(), lastSent: s.lastSent }))
          // 用户回答已由 sidecar 落为 user message，拉取真值
          queryClient.invalidateQueries({ queryKey: ['messages', convId] })
        } catch (e) {
          // 409 = 已在续跑（连点/竞态窗口），静默即可
          if ((e as Error & { status?: number }).status === 409) return
          setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }))
          throw e
        }
        return
      }
      if (state.running) return
      setState((s) => ({ ...s, lastSent: content }))
      try {
        await sendMessage(convId, content)
        // user 消息已由 sidecar 落库，拉取真值
        queryClient.invalidateQueries({ queryKey: ['messages', convId] })
      } catch (e) {
        // 发送失败（如 409 同会话并发）：展示错误并抛出，让调用方恢复输入框
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }))
        throw e
      }
    },
    [convId, state.running, state.interrupt, queryClient],
  )

  /** HITL 审批卡的按钮裁决：全部动作统一 approve / reject（每个动作一个 decision）。 */
  const decide = useCallback(
    async (decisions: HitlDecision[]) => {
      if (!state.interrupt || state.running) return
      const runId = state.interrupt.runId
      try {
        await resumeRun(runId, decisions)
        setState((s) => ({ ...INITIAL_STATE, running: true, runId, startedAt: Date.now(), lastSent: s.lastSent }))
      } catch (e) {
        // 409 = 已在续跑（双击竞态窗口），静默即可
        if ((e as Error & { status?: number }).status === 409) return
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }))
      }
    },
    [state.interrupt, state.running],
  )

  /** 用户主动停止：置位协作式取消，收敛由随后的 agent.error（「任务已停止」）完成。
   *  取消到真正终止之间存在事件边界等待（通常 1~2s），stopping 态让按钮转「正在停止…」。 */
  const cancel = useCallback(async () => {
    const rid = state.runId
    if (!rid || !state.running || state.stopping) return
    setState((s) => ({ ...s, stopping: true }))
    try {
      await cancelRun(rid)
    } catch {
      // 404/409 = run 已结束（竞态窗口）：随后的终态事件/对账会自行收敛，无需提示
    }
  }, [state.runId, state.running, state.stopping])

  return { ...state, send, decide, cancel }
}
