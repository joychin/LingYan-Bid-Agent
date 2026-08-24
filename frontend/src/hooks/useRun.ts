import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getLatestRun, sendMessage } from '@/api/client'
import { subscribeSSE, type TodoItem } from '@/api/sse'
import { useSidecarHealth } from '@/context/SidecarHealth'

export interface ToolStep {
  id: string
  tool: string
  args: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  summary: string
  error?: string
}

export interface RunState {
  running: boolean
  streamText: string
  reasoningText: string
  tools: ToolStep[]
  todos: TodoItem[]
  done: number
  total: number
  error: string | null
  /** 最近一次发送的文本：发送失败重试用（此时用户消息可能未落库，不能从消息列表取） */
  lastSent: string
}

const INITIAL_STATE: RunState = {
  running: false,
  streamText: '',
  reasoningText: '',
  tools: [],
  todos: [],
  done: 0,
  total: 0,
  error: null,
  lastSent: '',
}

/** 收敛已结束的 run：只有处于 running 态时才动作，避免历史 run 的 run.state 反复打扰 */
function convergeRun(s: RunState, error: string | null): RunState {
  if (!s.running) return s
  return { ...INITIAL_STATE, lastSent: s.lastSent, error }
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

  useEffect(() => {
    if (!convId) return
    seqRef.current = 0
    terminalRunsRef.current = new Set()
    lastReconcileRef.current = 0
    setState(INITIAL_STATE)
    const ctrl = subscribeSSE(convId, {
      onEvent: (event, data) => {
        if (data.conversation_id !== convId) return
        switch (event) {
          case 'agent.started':
            setState((s) => ({ ...INITIAL_STATE, running: true, lastSent: s.lastSent }))
            break
          case 'agent.token':
            setState((s) => ({ ...s, streamText: s.streamText + (data.text ?? '') }))
            break
          case 'agent.reasoning':
            // 推理模型的 chain-of-thought 增量；非推理模型无此事件
            setState((s) => ({ ...s, reasoningText: s.reasoningText + (data.reasoning ?? '') }))
            break
          case 'tool.called': {
            const id = `${Date.now()}-${seqRef.current++}`
            setState((s) => ({
              ...s,
              tools: [...s.tools, { id, tool: data.tool ?? 'unknown', args: data.args ?? {}, status: 'running', summary: '' }],
            }))
            break
          }
          case 'tool.result':
            setState((s) => {
              const tools = [...s.tools]
              for (let i = tools.length - 1; i >= 0; i--) {
                if (tools[i].tool === data.tool && tools[i].status === 'running') {
                  const isError = !!data.error
                  tools[i] = {
                    ...tools[i],
                    status: isError ? 'error' : 'done',
                    summary: data.summary ?? '',
                    error: data.error,
                  }
                  break
                }
              }
              return { ...s, tools }
            })
            break
          case 'todo.updated':
            setState((s) => ({ ...s, todos: data.items ?? [], done: data.done ?? 0, total: data.total ?? 0 }))
            break
          case 'artifact.created':
            // 产物已落库，刷新列表让 ArtifactCard 即时出现
            void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
            break
          case 'run.state': {
            // 连接建立时的对账（sidecar 不补发历史事件）：
            // 在跑则恢复 running（重连/新挂载错过 agent.started），已结束则收敛
            if (data.status === 'running') {
              if (!terminalRunsRef.current.has(data.run_id)) {
                setState((s) => ({ ...s, running: true, error: null }))
              }
            } else {
              const err = data.status === 'error' ? (data.error ?? '任务已中断') : null
              setState((s) => convergeRun(s, err))
              // 收敛时拉真值（run 已结束但客户端错过了 completed/error 事件）
              void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
            }
            break
          }
          case 'agent.completed':
            terminalRunsRef.current.add(data.run_id)
            // 等落库消息拉回后再撤掉流式气泡：避免「清空->闪空->再出现」，
            // 流式累积文本与落库内容一致，替换是无缝的
            void queryClient
              .invalidateQueries({ queryKey: ['messages', convId] })
              .then(() => setState((s) => ({ ...s, running: false, streamText: '', reasoningText: '', error: null })))
            break
          case 'agent.error':
            terminalRunsRef.current.add(data.run_id)
            setState((s) => ({ ...s, running: false, error: data.error ?? '未知错误' }))
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
            if (run && run.status === 'running') return // 任务仍在执行：保持现状等事件
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
      if (!convId || state.running) return
      const content = text.trim()
      if (!content) return
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
    [convId, state.running, queryClient],
  )

  return { ...state, send }
}
