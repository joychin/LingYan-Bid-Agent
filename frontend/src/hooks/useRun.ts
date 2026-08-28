import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getLatestRun, resumeRun, cancelRun, sendMessage, type HitlDecision, type ThinkingLevel } from '@/api/client'
import { subscribeSSE, type ToolStep } from '@/api/sse'
import { useSidecarHealth } from '@/context/SidecarHealth'
import { INITIAL_STATE, runReducer, type Action, type RunState } from './runReducer'

export type { ToolStep }
export type { RunState }

/** 订阅会话事件流并驱动一个正在进行的 run（agent.started -> token… -> completed）。
 *
 * 事件 → 状态的全部决策在 ./runReducer（纯函数，vitest 事件回放覆盖）；本 hook 是薄执行层：
 * 订阅、HTTP 调用、以及 reducer 返回的 Effect（react-query 失效 / 拉回消息后再收敛）。
 * stateRef 与 useState 手动同轨：dispatch 同步算出下一状态（含副作用决策依赖的记账字段），
 * 不依赖 React 异步的 setState updater（StrictMode 下 updater 双调用会重复触发副作用收集）。
 */
export function useRun(convId: string | null) {
  const queryClient = useQueryClient()
  const { reconnectSeq } = useSidecarHealth()
  const [state, setState] = useState<RunState>(INITIAL_STATE)
  const stateRef = useRef<RunState>(INITIAL_STATE)
  // SSE 断线对账的限频记号（2s 内只查一次最新 run）
  const lastReconcileRef = useRef(0)

  const dispatchRef = useRef<(a: Action) => void>(() => {})

  const dispatch = useCallback(
    (action: Action) => {
      const { state: next, effects } = runReducer(stateRef.current, action)
      stateRef.current = next
      setState(next)
      // 副作用执行层：决策（何时失效/何时收敛）全在 reducer，这里只做 IO
      for (const e of effects) {
        if (e.kind === 'invalidate') {
          void queryClient.invalidateQueries({ queryKey: e.queryKey })
        } else if (e.kind === 'invalidate-messages') {
          void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
        } else {
          void queryClient
            .invalidateQueries({ queryKey: ['messages', convId] })
            .then(() => dispatchRef.current(e.action))
        }
      }
    },
    [convId, queryClient],
  )
  dispatchRef.current = dispatch

  useEffect(() => {
    if (!convId) return
    // 换会话重挂：状态与记账全部复位（terminalRuns 属于会话生命周期）
    stateRef.current = INITIAL_STATE
    setState(INITIAL_STATE)
    lastReconcileRef.current = 0
    const ctrl = subscribeSSE(convId, {
      onEvent: (event, data) => {
        if (data.conversation_id !== convId) return
        dispatch({ type: 'sse', event, data, now: Date.now() })
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
            dispatch({ type: 'reconcile-converge', error: err })
            void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
          })
          .catch(() => {
            /* sidecar 暂不可达：保持现状，等重连或健康探活恢复 */
          })
      },
    })
    return () => ctrl.abort()
    // reconnectSeq 递增（sidecar 恢复/换端口）时重挂流
  }, [convId, queryClient, reconnectSeq, dispatch])

  const send = useCallback(
    async (text: string, thinking: ThinkingLevel = 'low', model?: string) => {
      if (!convId) return
      const content = text.trim()
      if (!content) return
      const cur = stateRef.current
      // HITL 等待中：输入框的回答 = respond 决策（代替工具执行，回答合成为工具结果续跑）；
      // 续跑沿用 run 存档的思考档位/模型，此处 thinking/model 不参与
      if (cur.interrupt) {
        const runId = cur.interrupt.runId
        dispatch({ type: 'remember-sent', text: content })
        try {
          await resumeRun(runId, [{ type: 'respond', message: content }])
          // 乐观置 running（真正的 agent.started 随后到达并做同样的事），
          // 封住「202 到 started 之间」的发送窗口
          dispatch({ type: 'started', runId, now: Date.now() })
          // 用户回答已由 sidecar 落为 user message，拉取真值
          void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
        } catch (e) {
          // 409 = 已在续跑（连点/竞态窗口）：不置错误卡（run 确实在跑），但向上抛——
          // InputComposer 据此保留输入，静默 resolve 会把用户刚打的回答清掉
          if ((e as Error & { status?: number }).status === 409) throw e
          dispatch({ type: 'send-failed', error: e instanceof Error ? e.message : String(e) })
          throw e
        }
        return
      }
      if (cur.running) return
      dispatch({ type: 'remember-sent', text: content })
      try {
        await sendMessage(convId, content, thinking, model)
        // user 消息已由 sidecar 落库，拉取真值
        queryClient.invalidateQueries({ queryKey: ['messages', convId] })
      } catch (e) {
        // 发送失败（如 409 同会话并发）：展示错误并抛出，让调用方恢复输入框
        dispatch({ type: 'send-failed', error: e instanceof Error ? e.message : String(e) })
        throw e
      }
    },
    [convId, queryClient, dispatch],
  )

  /** HITL 审批卡的按钮裁决：全部动作统一 approve / reject（每个动作一个 decision）。
   *  返回是否已续跑（409=已在续跑亦视为成功）：调用方据此决定是否清理随附状态
   *  （如 wizard 提交成功后才 acknowledge 上传告知）。 */
  const decide = useCallback(
    async (decisions: HitlDecision[]): Promise<boolean> => {
      const cur = stateRef.current
      if (!cur.interrupt || cur.running) return false
      const runId = cur.interrupt.runId
      try {
        await resumeRun(runId, decisions)
        dispatch({ type: 'started', runId, now: Date.now() })
        return true
      } catch (e) {
        // 409 = 已在续跑（双击竞态窗口），静默且视为成功
        if ((e as Error & { status?: number }).status === 409) return true
        dispatch({ type: 'send-failed', error: e instanceof Error ? e.message : String(e) })
        return false
      }
    },
    [dispatch],
  )

  /** 用户主动停止：置位协作式取消，收敛由随后的 agent.error（「任务已停止」）完成。
   *  取消到真正终止之间存在事件边界等待（通常 1~2s），stopping 态让按钮转「正在停止…」。 */
  const cancel = useCallback(async () => {
    const cur = stateRef.current
    if (!cur.runId || !cur.running || cur.stopping) return
    dispatch({ type: 'stop-requested' })
    try {
      await cancelRun(cur.runId)
    } catch (e) {
      // 404/409 = run 已结束（竞态窗口）：随后的终态事件/对账会自行收敛，无需提示
      const status = (e as Error & { status?: number }).status
      if (status === 404 || status === 409) return
      // 网络层失败（请求未达 sidecar）：复位 stopping 解除按钮锁死，允许重试；
      // run 若仍在跑，随后的终态事件/对账照常收敛
      dispatch({ type: 'stop-failed' })
    }
  }, [dispatch])

  return { ...state, send, decide, cancel }
}
