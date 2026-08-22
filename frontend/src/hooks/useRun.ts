import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { sendMessage } from '@/api/client'
import { subscribeSSE } from '@/api/sse'

export interface ToolStep {
  id: string
  tool: string
  args: Record<string, unknown>
  status: 'running' | 'done'
  summary: string
}

export interface RunState {
  running: boolean
  streamText: string
  tools: ToolStep[]
  error: string | null
}

/** 订阅会话事件流并驱动一个正在进行的 run（agent.started → token… → completed）。 */
export function useRun(convId: string | null) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<RunState>({ running: false, streamText: '', tools: [], error: null })
  const seqRef = useRef(0)

  useEffect(() => {
    if (!convId) return
    seqRef.current = 0
    setState({ running: false, streamText: '', tools: [], error: null })
    const ctrl = subscribeSSE(convId, {
      onEvent: (event, data) => {
        if (data.conversation_id !== convId) return
        switch (event) {
          case 'agent.started':
            setState({ running: true, streamText: '', tools: [], error: null })
            break
          case 'agent.token':
            setState((s) => ({ ...s, streamText: s.streamText + (data.text ?? '') }))
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
                  tools[i] = { ...tools[i], status: 'done', summary: data.summary ?? '' }
                  break
                }
              }
              return { ...s, tools }
            })
            break
          case 'agent.completed':
            // 等落库消息拉回后再撤掉流式气泡：避免「清空→闪空→再出现」，
            // 流式累积文本与落库内容一致，替换是无缝的
            void queryClient
              .invalidateQueries({ queryKey: ['messages', convId] })
              .then(() => setState((s) => ({ ...s, running: false, streamText: '' })))
            break
          case 'agent.error':
            setState((s) => ({ ...s, running: false, error: data.error ?? '未知错误' }))
            break
        }
      },
      onError: (err) => {
        // 断线（尤其 sidecar 重启换端口后旧连接永久失效）时收敛 UI，避免 running 永久卡死；
        // 任务若仍在后台执行，重连后的事件流会把状态拉回
        setState((s) => ({
          ...s,
          running: false,
          error: `事件流连接中断：${err.message}（已重新拉取历史，若任务仍执行中请稍候）`,
        }))
        queryClient.invalidateQueries({ queryKey: ['messages', convId] })
      },
    })
    return () => ctrl.abort()
  }, [convId, queryClient])

  const send = useCallback(
    async (text: string) => {
      if (!convId || state.running) return
      const content = text.trim()
      if (!content) return
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
