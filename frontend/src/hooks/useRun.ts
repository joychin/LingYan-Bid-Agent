import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getLatestRun, getRunSnapshot, resumeRun, cancelRun, continueRun as continueRunApi, sendMessage, type HitlDecision, type ThinkingLevel } from '@/api/client'
import { subscribeSSE, type ToolStep } from '@/api/sse'
import { useSidecarHealth } from '@/context/SidecarHealth'
import { useToast } from '@/context/Toast'
import { INITIAL_STATE, runReducer, type Action, type RunState } from './runReducer'

export type { ToolStep }
export type { RunState }

/** 流式高频事件的合并窗口（ms）：token/思考增量最多每 200ms 应用进 React state 一次，
 *  与渲染层 useThrottledValue 的节流档一致。 */
const STREAM_BATCH_MS = 200

/** 过程对账拉取的限频间隔（ms）：seq 缺口在洪峰下会连环触发（连环跳号），
 *  全树快照不便宜，5s 内只拉一次。 */
const TRACE_PULL_MIN_INTERVAL = 5000

/** 对账拉取失败后的自动重试延迟（ms）：比限频窗长一拍；重试仍失败才升级为可见提示。 */
const TRACE_SYNC_RETRY_MS = 6000

/** 合并窗口内攒下的流式增量（tokens=正文；mainReasoning=主 agent 思考；
 *  byAgent=各子代理思考，键=task 的 tool_call_id）。 */
interface StreamBatch {
  tokens: string
  mainReasoning: string
  byAgent: Map<string, string>
  /** 缓冲事件的最高 seq（flush 时续接去重水位） */
  maxSeq: number
  seqRunId: string | null
  /** 本批首帧的 seq_from（SSE 微合批 additive）：连续性锚点，flush 交给 reducer
   *  区分「服务端合并跳号」与「真丢事件」（后者才触发过程对账） */
  seqFrom: number | null
}

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
  const { toast } = useToast()
  const [state, setState] = useState<RunState>(INITIAL_STATE)
  const stateRef = useRef<RunState>(INITIAL_STATE)
  // SSE 断线对账的限频记号（2s 内只查一次最新 run）
  const lastReconcileRef = useRef(0)
  // 过程对账快照拉取的限频记号（5s，见 TRACE_PULL_MIN_INTERVAL）
  const lastTracePullRef = useRef(0)
  // 对账失败自动重试的记账：runId=已安排过一次重试的 run（每 run 每挂载一次），
  // 定时器 id 供卸载清理（重试跨会话切换时由 runId 守卫拦下）
  const traceSyncRetryRef = useRef<string | null>(null)
  const traceSyncTimerRef = useRef<number | null>(null)
  // 流式合并缓冲与窗口定时器（见 dispatch 内说明）
  const batchRef = useRef<StreamBatch | null>(null)
  const batchTimerRef = useRef<number | null>(null)

  const dispatchRef = useRef<(a: Action) => void>(() => {})
  // 过程对账拉取的转发：effect 执行（applyAction）先于 restoreSnapshot 定义，照 dispatchRef 先例
  const restoreSnapshotRef = useRef<(runId: string) => void>(() => {})

  /** reducer 应用层（原 dispatch 主体）：同步算下一状态 + 执行 Effect。 */
  const applyAction = useCallback(
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
        } else if (e.kind === 'reconcile-trace') {
          // seq 缺口 = SSE 丢过事件：拉运行快照补死步（限频在 restoreSnapshot 内）
          restoreSnapshotRef.current(e.runId)
        } else {
          void queryClient
            .invalidateQueries({ queryKey: ['messages', convId] })
            .then(() => dispatchRef.current(e.action))
        }
      }
    },
    [convId, queryClient],
  )

  /** 冲刷流式合并缓冲：攒下的 token/思考增量合成一次 stream-batch 应用。 */
  const flushStreamBatch = useCallback(() => {
    if (batchTimerRef.current != null) {
      clearTimeout(batchTimerRef.current)
      batchTimerRef.current = null
    }
    const b = batchRef.current
    batchRef.current = null
    if (!b) return
    const deltas: Array<{ agentId: string | null; text: string }> = []
    if (b.mainReasoning) deltas.push({ agentId: null, text: b.mainReasoning })
    for (const [agentId, text] of b.byAgent) deltas.push({ agentId, text })
    if (!b.tokens && deltas.length === 0) return
    applyAction({
      type: 'stream-batch',
      tokens: b.tokens,
      deltas,
      ...(b.seqRunId && b.maxSeq > 0
        ? { seq: { runId: b.seqRunId, seq: b.maxSeq, seqFrom: b.seqFrom ?? b.maxSeq } }
        : {}),
    })
  }, [applyAction])

  const dispatch = useCallback(
    (action: Action) => {
      // 流式高频事件合并：逐 token dispatch 会让 ChatView 每 token 重渲染一次
      // （子代理 reasoning 还带整棵工具树的递归拷贝，长 run 二次方退化）。空闲后的
      // 首个事件立即应用（首字不迟滞），其后 200ms 窗口内的增量攒成一次应用；
      // 其他任何 action 到达前先冲刷缓冲——封段（tool.called 读 streamText/
      // reasoningText）、收敛、快照都依赖缓冲文本先落地，事件间相对顺序不变。
      if (action.type === 'sse' && (action.event === 'agent.token' || action.event === 'agent.reasoning')) {
        const { event, data } = action
        // seq 去重与 reducer 同规则：缓冲期 lastSeq 未推进，与缓冲内最大 seq 一并比对
        if (typeof data.seq === 'number') {
          const last = stateRef.current.lastSeq
          const b = batchRef.current
          const seen = Math.max(
            last && last.runId === data.run_id ? last.seq : 0,
            b && b.seqRunId === data.run_id ? b.maxSeq : 0,
          )
          if (data.seq <= seen) return
        }
        if (batchTimerRef.current == null) {
          applyAction(action)
          batchTimerRef.current = window.setTimeout(() => {
            batchTimerRef.current = null
            flushStreamBatch()
          }, STREAM_BATCH_MS)
          return
        }
        const b = (batchRef.current ??= {
          tokens: '',
          mainReasoning: '',
          byAgent: new Map(),
          maxSeq: 0,
          seqRunId: null,
          seqFrom: null,
        })
        if (typeof data.seq === 'number') {
          b.maxSeq = Math.max(b.maxSeq, data.seq)
          b.seqRunId = data.run_id
          if (b.seqFrom == null) b.seqFrom = data.seq_from ?? data.seq
        }
        if (event === 'agent.token') {
          b.tokens += data.text ?? ''
        } else if (data.agent_id) {
          b.byAgent.set(data.agent_id, (b.byAgent.get(data.agent_id) ?? '') + (data.text ?? ''))
        } else {
          b.mainReasoning += data.text ?? ''
        }
        return
      }
      flushStreamBatch()
      applyAction(action)
    },
    [applyAction, flushStreamBatch],
  )
  dispatchRef.current = dispatch

  /** 过程对账拉取（5s 限频）：本地树空 = 重挂/刷新恢复（reducer 全量替换，含 waiting_input
   *  冻结）；树非空 = SSE 丢过事件的死步/丢步骤补齐（reducer 字段级 merge，2026-09-08
   *  过程对账——此前「树非空不拉」的闸让洪峰/断连丢事件后的假「运行中/启动中」卡永远
   *  无法自愈）。触发：重连对账（run.state/reconcile）与 seq 缺口 effect。 */
  const restoreSnapshot = useCallback(
    (runId: string) => {
      if (Date.now() - lastTracePullRef.current < TRACE_PULL_MIN_INTERVAL) return
      lastTracePullRef.current = Date.now()
      void getRunSnapshot(runId)
        .then((snapshot) => {
          const current = stateRef.current
          // 调用侧守卫（reducer 内还有同口径第二道闸）：已切到别的 run 不应用。
          // running 恢复执行卡，waiting_input 恢复冻结卡（等待期刷新/重连）。
          // runId 为 null 允许--断线重挂时 run.state 可能还没到，快照本身带权威 runId。
          if (
            (snapshot.status !== 'running' && snapshot.status !== 'waiting_input') ||
            (current.runId && current.runId !== runId)
          )
            return
          traceSyncRetryRef.current = null
          dispatch({
            type: 'snapshot',
            runId,
            status: snapshot.status,
            tools: snapshot.tools,
            todos: snapshot.todos,
            reasoningText: snapshot.reasoning ?? '',
            snapshotSeq: snapshot.last_seq ?? undefined,
          })
        })
        .catch(() => {
          /* snapshot 是恢复增强，SSE 主链路失败时保持现有状态——但不再全静默
           * （2026-09-12）：失败意味着死步/假「运行中」可能补不回来。首败 6s 后自动
           * 重试一次；重试仍败置 traceSyncIssue，过程区折叠头出提示行给用户手动出口。 */
          console.warn(`[trace] 过程快照拉取失败：${runId}`)
          if (traceSyncRetryRef.current !== runId) {
            traceSyncRetryRef.current = runId
            traceSyncTimerRef.current = window.setTimeout(() => {
              traceSyncTimerRef.current = null
              lastTracePullRef.current = 0
              restoreSnapshotRef.current(runId)
            }, TRACE_SYNC_RETRY_MS)
            return
          }
          dispatchRef.current({ type: 'trace-sync-failed' })
        })
    },
    [dispatch],
  )
  restoreSnapshotRef.current = restoreSnapshot

  /** 过程区「重新同步」按钮（traceSyncIssue 提示行）的落点：绕限频强制重拉当前 run。 */
  const resyncTrace = useCallback(() => {
    const rid = stateRef.current.runId ?? stateRef.current.interrupt?.runId ?? null
    if (!rid) return
    lastTracePullRef.current = 0
    traceSyncRetryRef.current = null
    restoreSnapshot(rid)
  }, [restoreSnapshot])

  /** 限频 best-effort 对账：查最新 run，确认已结束才收敛本地状态。
   *  SSE onError（断线对账）与 cancel 的 404/409（run 已结束/收尾竞态窗口）共用——
   *  后者不能只等 SSE 终态事件：SSE 半开/断开时终态永不到达，stopping 会把发送钮
   *  永久锁在「正在停止…」。对账确认仍在跑则保持现状（waiting_input 由 run.state 恢复卡）。 */
  const reconcile = useCallback(async () => {
    if (!convId) return
    if (Date.now() - lastReconcileRef.current < 2000) return
    lastReconcileRef.current = Date.now()
    try {
      const { run } = await getLatestRun(convId)
      if (run && (run.status === 'running' || run.status === 'waiting_input')) {
        // 先走 run.state 语义（复用 SSE 对账分支：恢复 running / 等待卡含 requests、
        // 清陈旧 error）再拉快照——快照分支不置 interrupt，只调快照的话等待态恢复出
        // 冻结树却没有回答卡，用户无动作入口。与 SSE 重连路径的事件顺序一致。
        // started_at 缺省走 reducer 兜底（此恢复路径计时起点小失真，接受）。
        dispatch({
          type: 'sse',
          event: 'run.state',
          now: Date.now(),
          data: {
            run_id: run.id,
            conversation_id: convId,
            status: run.status,
            ...(run.status === 'waiting_input' ? { requests: run.requests ?? [] } : {}),
          },
        })
        // 树空=恢复活卡；树非空=对账补死步（断连窗口丢过事件的场景，2026-09-08）
        restoreSnapshot(run.id)
        return
      }
      const err = run && run.status === 'error' ? (run.error ?? '任务已中断') : null
      dispatch({ type: 'reconcile-converge', error: err, runId: run?.id })
      void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
    } catch {
      /* sidecar 暂不可达：保持现状，等重连或健康探活恢复 */
    }
  }, [convId, queryClient, dispatch, restoreSnapshot])

  useEffect(() => {
    if (!convId) return
    // 换会话重挂：状态与记账全部复位（terminalRuns 属于会话生命周期）
    stateRef.current = INITIAL_STATE
    setState(INITIAL_STATE)
    lastReconcileRef.current = 0
    lastTracePullRef.current = 0
    const ctrl = subscribeSSE(convId, {
      onEvent: (event, data) => {
        if (data.conversation_id !== convId) return
        dispatch({ type: 'sse', event, data, now: Date.now() })
        // 断线/重挂对账：run.state=running（恢复执行卡）或 waiting_input（恢复冻结卡）
        // 即拉一次运行快照——树空走全量恢复，树非空走 merge 补死步（断连窗口丢过事件）。
        if (event === 'run.state' && (data.status === 'running' || data.status === 'waiting_input')) {
          restoreSnapshot(data.run_id)
        }
      },
      onError: () => {
        // 连接失败 ≠ 任务失败：不能把 running 置 false--重连后没有 agent.started 补发，
        // 流式 UI 会永久丢失且用户可再发消息（后端 409）。fetch-event-source 会自动重连，
        // 恢复由连接建立时的 run.state 对账事件完成；sidecar 存活状态由 SidecarBanner 呈现。
        // 这里只做限频的 best-effort 对账（sidecar 重启等场景）。
        void reconcile()
      },
    })
    return () => {
      ctrl.abort()
      // 丢弃未冲刷的流式缓冲（状态随 effect 重置，冲刷无意义）并清掉窗口定时器
      if (batchTimerRef.current != null) {
        clearTimeout(batchTimerRef.current)
        batchTimerRef.current = null
      }
      batchRef.current = null
      if (traceSyncTimerRef.current != null) {
        clearTimeout(traceSyncTimerRef.current)
        traceSyncTimerRef.current = null
      }
      traceSyncRetryRef.current = null
    }
    // reconnectSeq 递增（sidecar 恢复/换端口）时重挂流
  }, [convId, queryClient, reconnectSeq, dispatch, restoreSnapshot, reconcile])

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
        dispatch({ type: 'remember-answer', text: content })
        try {
          await resumeRun(runId, [{ type: 'respond', message: content }])
          // 乐观置 running（真正的 agent.started 随后到达并做同样的事），
          // 封住「202 到 started 之间」的发送窗口；continuation 标记续跑段
          // （RunMessage 去掉回合头、紧贴暂停消息渲染）
          dispatch({ type: 'started', runId, now: Date.now(), continuation: true, continuationKind: 'answer' })
          // 用户回答已由 sidecar 落为 user message，拉取真值
          void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
          // 续跑立即使占用清单失效：侧栏 loader 不等 3s 轮询周期
          void queryClient.invalidateQueries({ queryKey: ['runs', 'active'] })
          restoreSnapshot(runId)
        } catch (e) {
          // 409 = 已在续跑（连点/竞态窗口），不置错误卡（run 确实在跑），但向上抛——
          // InputComposer 据此保留输入，静默 resolve 会把用户刚打的回答清掉。
          // 409 也可能是 run 已被别处终止的「不在等待输入」——强制对账一次，
          // 等待死卡出口（reconcile-converge 带 runId）负责终态收敛
          if ((e as Error & { status?: number }).status === 409) {
            lastReconcileRef.current = 0
            void reconcile()
            throw e
          }
          dispatch({ type: 'send-failed', error: e instanceof Error ? e.message : String(e) })
          throw e
        }
        return
      }
      if (cur.running) return
      dispatch({ type: 'remember-instruction', text: content })
      try {
        await sendMessage(convId, content, thinking, model)
        // user 消息已由 sidecar 落库，拉取真值
        queryClient.invalidateQueries({ queryKey: ['messages', convId] })
        // 发送立即使占用清单失效：侧栏 loader 不等 3s 轮询周期
        void queryClient.invalidateQueries({ queryKey: ['runs', 'active'] })
      } catch (e) {
        if ((e as Error & { status?: number }).status === 409) {
          // 409 = 后端有活 run（running/waiting_input）而本地不知——状态滞后不是故障
          // （守卫空窗：重挂对账未达/202 后 started 未达）。对账恢复真实状态 + 轻提示，
          // 不置错误卡（「报错了还在跑」的误导源，2026-09-10 测查后修订）。抛出保留输入。
          // toast 用服务端 detail（2026-09-12）：「正在等待你的回答/确认」这类原因能指路，
          // 固定文案把 waiting 死锁的出路信息丢了。
          lastReconcileRef.current = 0 // 绕过限频（cancel 路径同款先例）
          void reconcile()
          const detail = e instanceof Error ? e.message.trim() : ''
          toast(detail || '任务进行中，这条消息没有发出')
          throw e
        }
        // 发送失败（网络/服务错误）：展示错误并抛出，让调用方恢复输入框
        dispatch({ type: 'send-failed', error: e instanceof Error ? e.message : String(e) })
        throw e
      }
    },
    [convId, queryClient, dispatch, reconcile, toast],
  )

  /** HITL 审批卡的按钮裁决：全部动作统一 approve / reject（每个动作一个 decision）。
   *  返回是否已续跑（409=已在续跑亦视为成功）：调用方据此决定是否清理随附状态
   *  （如 wizard 提交成功后才 acknowledge 上传告知）。 */
  const decide = useCallback(
    async (decisions: HitlDecision[]): Promise<boolean> => {
      const cur = stateRef.current
      if (!cur.interrupt || cur.running) return false
      const runId = cur.interrupt.runId
      // respond 回答记入 continuationAnswer：续跑流式气泡的临时回答行数据源。
      const respondText = decisions
        .filter((d): d is Extract<HitlDecision, { type: 'respond' }> => d.type === 'respond')
        .map((d) => d.message.trim())
        .filter(Boolean)
        .join('\n')
      try {
        await resumeRun(runId, decisions)
        dispatch({ type: 'remember-answer', text: respondText })
        dispatch({
          type: 'started',
          runId,
          now: Date.now(),
          continuation: true,
          continuationKind: respondText ? 'answer' : 'subagents',
        })
        void queryClient.invalidateQueries({ queryKey: ['runs', 'active'] })
        restoreSnapshot(runId)
        return true
      } catch (e) {
        // 409 多数是已在续跑（双击竞态窗口），静默且视为成功；但也可能是 run 已被
        // 别处终止后的「不在等待输入」——强制对账一次，等待死卡出口（reconcile-
        // converge 带 runId）负责终态收敛，确认在跑则对账恢复真实状态
        if ((e as Error & { status?: number }).status === 409) {
          lastReconcileRef.current = 0
          void reconcile()
          return true
        }
        dispatch({ type: 'send-failed', error: e instanceof Error ? e.message : String(e) })
        return false
      }
    },
    [dispatch, queryClient, restoreSnapshot, reconcile],
  )

  /** 用户主动停止：置位协作式取消，收敛由随后的 agent.error（「任务已停止」）完成。
   *  取消到真正终止之间存在事件边界等待（通常 1~2s），stopping 态让按钮转「正在停止…」。
   *  waiting_input（2026-09-08 逃生口）：端点直接落终态并回发 agent.error——202 后
   *  本地 settle-error 兜底收敛（SSE 半开时终态事件到不了，冻结的问答卡清不掉；
   *  不能靠 reconcile：convergeRun 的 !running 守卫对等待态无能为力；双保险幂等）。 */
  const cancel = useCallback(async () => {
    const cur = stateRef.current
    if (cur.stopping) return
    // 目标 run：执行中用 runId；等待输入用 interrupt.runId（此时 running=false）
    const waiting = !cur.running
    const targetRun = waiting ? cur.interrupt?.runId : cur.runId
    if (!targetRun) return
    if (!waiting) dispatch({ type: 'stop-requested' })
    try {
      await cancelRun(targetRun)
      if (waiting) {
        dispatch({ type: 'settle-error', error: '任务已停止', code: 'cancelled' })
        void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
        void queryClient.invalidateQueries({ queryKey: ['runs', 'active'] })
      }
    } catch (e) {
      const status = (e as Error & { status?: number }).status
      if (status === 404 || status === 409) {
        if (waiting) {
          // 等待卡撞 404/409（2026-09-10 review）= run 已不在服务端等待态（别处
          // 终止/收尾竞态）——本地按已停止收敛（SSE 半开时终态事件到不了；
          // settle-error 幂等，终态事件后到不冲突）。此前直接 return 是死卡死角
          dispatch({ type: 'settle-error', error: '任务已停止', code: 'cancelled' })
          void queryClient.invalidateQueries({ queryKey: ['messages', convId] })
          void queryClient.invalidateQueries({ queryKey: ['runs', 'active'] })
          return
        }
        // 404/409 = run 已结束/正在收尾的竞态窗口（或与续跑撞车——用户恰在此刻
        // 提交回答）：主动对账收敛，不能只依赖 SSE 终态（半开/断开时没有终态
        // 事件，stopping 会把发送钮永久锁在「正在停止…」）。绕过限频（用户刚
        // 点过停止，此刻的对账不该被吞）；对账确认仍在跑则保持 stopping。
        lastReconcileRef.current = 0
        void reconcile()
        return
      }
      // 网络层失败（请求未达 sidecar）：复位 stopping 解除按钮锁死，允许重试；
      // run 若仍在跑，随后的终态事件/对账照常收敛
      dispatch({ type: 'stop-failed' })
    }
  }, [convId, dispatch, queryClient, reconcile])

  /** 终态断点续跑（2026-09-12）：error 终态且定性可续（interrupted/llm_unavailable/
   *  llm_auth）的 run 从 checkpoint 续跑——不重发消息、已完成的工作不重跑。rid 缺省
   *  用当前 runId（会话内点错误卡按钮）；刷新后的历史入口由调用方传入目标 run id。
   *  乐观置 running 同 decide（202 到 SSE started 之间的发送窗口封住）；409 = 状态
   *  已变（别处续跑/会话已前进/checkpoint 缺失），强制对账收敛并透传服务端原因。 */
  const continueRun = useCallback(
    async (rid?: string) => {
      const cur = stateRef.current
      const target = rid ?? cur.runId
      if (!target || cur.running || cur.interrupt) return
      try {
        await continueRunApi(target)
        dispatch({ type: 'started', runId: target, now: Date.now(), continuation: true })
        void queryClient.invalidateQueries({ queryKey: ['runs', 'active'] })
        restoreSnapshot(target)
      } catch (e) {
        if ((e as Error & { status?: number }).status === 409) {
          lastReconcileRef.current = 0
          void reconcile()
          toast(e instanceof Error && e.message ? e.message : '该任务无法从断点继续', 'error')
          return
        }
        toast(e instanceof Error ? e.message : '从断点继续失败，请重试', 'error')
      }
    },
    [dispatch, queryClient, restoreSnapshot, reconcile, toast],
  )

  return { ...state, send, decide, cancel, continueRun, resyncTrace }
}
