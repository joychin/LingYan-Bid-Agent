/**
 * useRun 的纯 reducer：SSE 事件流 → RunState 的全部决策收口于此（可回放、可单测）。
 *
 * 设计：
 * - 记账字段（seq 去重 / terminalRuns / 步骤 id 计数）一并收进 state——整条事件管线
 *   用固定时钟即可在 vitest 里重放（见 __fixtures__/）。
 * - 副作用（react-query 失效、消息拉回后再收敛的时序）不在这里执行，而是以 Effect
 *   描述符返回，由 useRun 统一执行——决策单点化，hook 保持薄执行层。
 * - 「先 invalidate 拉回落库消息、再撤掉流式气泡」的既有时序用 settle-after-messages
 *   表达：等价于原 invalidateQueries().then(setState)。
 */

import type { AgentEventData, InterruptRequest, TodoItem, ToolStep } from '@/api/sse'

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
  /** 错误分类（agent.error/run.state additive code）：cancelled=用户主动停止，中性呈现 */
  errorCode: string | null
  /** 最近一次普通用户指令：发送失败/任务失败时重试用。 */
  lastInstruction: string
  /** 本次 HITL respond 的回答：仅在续跑空窗期显示，纯审批不产生。 */
  continuationAnswer: string
  /** 暂停时未封口的正文（settle-interrupt 从 streamText 移入）：活卡冻结期间渲染为
   *  过程区顶部旁白行——正文/思考/工具树在暂停全程不消失（一张活卡贯穿暂停与续跑）。 */
  pauseNarration: string
  /** HITL 暂停（run.interrupt / run.state 对账）：非空 = 有待用户裁决的动作，输入框切回答模式 */
  interrupt: { runId: string; requests: InterruptRequest[] } | null
  /** 本 running 态是否为 HITL 续跑段（批准/回答后的 resumed agent.started）：
   *  RunMessage 据此去掉回合头、紧贴暂停消息渲染（同一回合的视觉续接）。 */
  continuation: boolean
  /** 续跑类型：子代理审批续跑可在尚无实时 task 事件时显示启动中。 */
  continuationKind: 'subagents' | 'answer' | null
  /** seq 去重：当前 run 已接受的最高序列号（换 run 时按 runId 区分，seq=1 重新起算） */
  lastSeq: { runId: string; seq: number } | null
  /** 已通过 SSE 收到终态的 run：HTTP 对账拿到的过期 running 状态不再复活它 */
  terminalRuns: Set<string>
  /** 步骤 id 计数（与 now 组合生成稳定 id） */
  stepCounter: number
}

export const INITIAL_STATE: RunState = {
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
  errorCode: null,
  lastInstruction: '',
  continuationAnswer: '',
  pauseNarration: '',
  interrupt: null,
  continuation: false,
  continuationKind: null,
  lastSeq: null,
  terminalRuns: new Set(),
  stepCounter: 0,
}

export type Effect =
  /** 刷新 react-query 缓存（artifacts/conversations） */
  | { kind: 'invalidate'; queryKey: unknown[] }
  /** 拉回落库消息（invalidate ['messages', cid]，cid 由 hook 层补） */
  | { kind: 'invalidate-messages' }
  /** 拉回落库消息之后才 dispatch action（保「先对齐消息、再撤流式气泡」的时序） */
  | { kind: 'settle-after-messages'; action: Action }

export type Action =
  | { type: 'sse'; event: string; data: AgentEventData; now: number }
  /** run 开始（agent.started）与续跑乐观置 running（resume 202 与 agent.started 之间）共用；
   *  continuation=true 标记 HITL 续跑段（run 曾经 interrupt），sticky 保留——SSE 的
   *  agent.started 随后会以同 runId 再触发一次 started，不带标记会把续接态冲掉 */
  | { type: 'started'; runId: string; now: number; continuation?: boolean; continuationKind?: 'subagents' | 'answer' }
  | { type: 'settle-completed' }
  | { type: 'settle-error'; error: string; code: string | null }
  | { type: 'settle-interrupt'; runId: string; requests: InterruptRequest[] }
  | { type: 'remember-instruction'; text: string }
  | { type: 'remember-answer'; text: string }
  | { type: 'send-failed'; error: string }
  | { type: 'stop-requested' }
  | { type: 'stop-failed' }
  | {
      type: 'snapshot'
      runId: string
      /** 快照对应的 run 状态：非 running（已终态/等待输入）的快照不应用（reducer 内守卫） */
      status: 'running' | 'completed' | 'error' | 'waiting_input'
      tools: ToolStep[]
      todos: TodoItem[]
      reasoningText: string
      snapshotSeq?: number
    }
  /** SSE 断线后的 HTTP 对账收敛（getLatestRun 确认已结束才触发） */
  | { type: 'reconcile-converge'; error: string | null }

export interface ReducerResult {
  state: RunState
  effects: Effect[]
}

/** 收敛已结束的 run：只有处于 running 态时才动作，避免历史 run 的 run.state 反复打扰。
 * 记账字段随 INITIAL_STATE 复位（terminalRuns 也清：与「换会话重挂」语义一致）。 */
function convergeRun(s: RunState, error: string | null, errorCode: string | null = null): RunState {
  if (!s.running) return s
  return { ...INITIAL_STATE, lastInstruction: s.lastInstruction, error, errorCode }
}

function newStep(
  id: string,
  data: { tool?: string; args?: Record<string, unknown>; tool_call_id?: string | null },
  now: number,
): ToolStep {
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
    startedAt: now,
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

/** 不可变回填：按 tool_call_id（缺省退化按工具名）找执行中步骤写终态。
 *  paused 也匹配：续跑段 409 双窗口（SSE started 先到、乐观 revive 未发生）下，
 *  冻结步骤收到 tool.result 时服务端它确实在跑——照常回填终态。 */
function fillStep(
  steps: ToolStep[],
  data: { tool?: string; tool_call_id?: string | null; summary?: string; error?: string },
  now: number,
): ToolStep[] {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]
    if (s.status === 'running' || s.status === 'paused') {
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
            endedAt: now,
          },
          ...steps.slice(i + 1),
        ]
      }
    }
    if (s.children.length > 0) {
      const children = fillStep(s.children, data, now)
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

function revivePausedSteps(steps: ToolStep[]): ToolStep[] {
  return steps.map((step) => ({
    ...step,
    ...(step.status === 'paused' ? { status: 'running' as const, endedAt: null } : {}),
    children: step.children.length > 0 ? revivePausedSteps(step.children) : step.children,
  }))
}

/** 树里仍在 running 的步骤冻结为 paused（HITL 暂停快照，镜像 sidecar _freeze_paused_steps）：
 *  被门禁拦下的调用不会有 tool.result，不冻结会在活卡上永远转圈。 */
function freezeRunningSteps(steps: ToolStep[]): ToolStep[] {
  return steps.map((step) => ({
    ...step,
    ...(step.status === 'running' ? { status: 'paused' as const } : {}),
    children: step.children.length > 0 ? freezeRunningSteps(step.children) : step.children,
  }))
}

const result = (state: RunState, effects: Effect[] = []): ReducerResult => ({ state, effects })

export function runReducer(s: RunState, action: Action): ReducerResult {
  switch (action.type) {
    case 'sse':
      return reduceSse(s, action)
    case 'started': {
      const sameRun = s.runId === action.runId && s.runId !== null
      const base = sameRun ? s : INITIAL_STATE
      // 同一 run 的 HITL 续跑会再次发 agent.started；它是执行段的边界通知，
      // 不是新 run，不能清掉暂停快照里的 task 卡、todos 或 reasoning。
      return result({
        ...base,
        running: true,
        runId: action.runId,
        startedAt: sameRun ? (s.startedAt ?? action.now) : action.now,
        lastInstruction: s.lastInstruction,
        continuationAnswer: s.continuationAnswer,
        terminalRuns: s.terminalRuns,
        lastSeq: s.lastSeq,
        stepCounter: s.stepCounter,
        continuation: s.continuation || !!action.continuation,
        continuationKind: action.continuationKind ?? base.continuationKind,
        tools: action.continuation ? revivePausedSteps(base.tools) : base.tools,
        error: null,
        errorCode: null,
        interrupt: null,
        stopping: false,
        streamText: '',
      })
    }
    case 'settle-completed':
      // 等落库消息拉回后再撤掉流式气泡：避免「清空->闪空->再出现」（时序由 settle-after-messages 保证）
      return result({
        ...s,
        running: false,
        stopping: false,
        streamText: '',
        reasoningText: '',
        error: null,
        continuationAnswer: '',
        pauseNarration: '',
        interrupt: null,
        continuation: false,
        continuationKind: null,
      })
    case 'settle-error':
      // sidecar 已把中断 run 的半截回复落库（带「（任务中断）」标记）：拉回消息让 UI 与
      // 模型记忆对齐；清空流式气泡避免与落库消息双显
      return result({
        ...s,
        running: false,
        stopping: false,
        streamText: '',
        reasoningText: '',
        error: action.error,
        errorCode: action.code,
        continuationAnswer: '',
        pauseNarration: '',
        interrupt: null,
        continuation: false,
        continuationKind: null,
      })
    case 'settle-interrupt':
      // 活卡原地冻结（一张活卡贯穿暂停与续跑）：工具树保留（running 步骤冻结为 paused，
      // 被门禁拦下的调用不会有 tool.result）、思考流保留（续跑段自然追加）、未封口正文
      // 移入 pauseNarration 渲染为旁白行——都不清空不换卡。暂停消息由 sidecar 落库、
      // 活卡存续期间前端不渲染独立卡，终态时被最终/中断消息吸收（MessageList 装配）。
      return result({
        ...s,
        running: false,
        stopping: false,
        streamText: '',
        pauseNarration: s.streamText,
        tools: freezeRunningSteps(s.tools),
        continuationAnswer: '',
        interrupt: { runId: action.runId, requests: action.requests },
        continuation: false,
        continuationKind: null,
      })
    case 'remember-instruction':
      return result({ ...s, lastInstruction: action.text, continuationAnswer: '' })
    case 'remember-answer':
      return result({ ...s, continuationAnswer: action.text })
    case 'send-failed':
      return result({ ...s, error: action.error, errorCode: null })
    case 'stop-requested':
      return result({ ...s, stopping: true })
    case 'stop-failed':
      // 网络层失败（请求未达 sidecar）：复位 stopping 解除按钮锁死，允许重试
      return result({ ...s, stopping: false })
    case 'snapshot': {
      // 快照守卫单点收口：终态快照不应用；已终态的 run 不被旧快照复活；已切走的当前
      // run 不被覆盖。waiting_input 快照恢复冻结树与思考（等待期刷新/重连重建活卡）
      // 但不置 running；调用侧（restoreSnapshot）只是第一道闸。
      if (action.status === 'completed' || action.status === 'error') return result(s)
      if (s.terminalRuns.has(action.runId)) return result(s)
      if (s.runId && s.runId !== action.runId) return result(s)
      // 快照 seq 取 max：runs.last_seq 运行中恒旧（只在暂停/终态回写），
      // 晚到的快照直接采用会把 lastSeq 回退、触发一次多余的缺口告警
      const snapSeq =
        action.snapshotSeq != null
          ? s.lastSeq && s.lastSeq.runId === action.runId
            ? Math.max(s.lastSeq.seq, action.snapshotSeq)
            : action.snapshotSeq
          : null
      return result({
        ...s,
        running: action.status === 'running' ? true : s.running,
        runId: action.runId,
        tools: s.continuation
          ? revivePausedSteps(action.tools)
          : action.status === 'waiting_input'
            ? // 防御性冻结：等待态快照按契约已是 paused 终态树，混入 running 也不转圈
              freezeRunningSteps(action.tools)
            : action.tools,
        todos: action.todos,
        reasoningText: action.reasoningText,
        ...(snapSeq != null ? { lastSeq: { runId: action.runId, seq: snapSeq } } : {}),
      })
    }
    case 'reconcile-converge':
      return result(convergeRun(s, action.error))
  }
}

function reduceSse(s: RunState, action: Extract<Action, { type: 'sse' }>): ReducerResult {
  const { event, data, now } = action
  // seq 去重（契约 additive 扩展）：双连接残留的重复投递直接丢弃（结构上终结重影）；
  // 缺口告警不重放（MVP 断线策略仍是重拉 messages）。无 seq（旧 sidecar/连接级事件）照常接受。
  if (typeof data.seq === 'number') {
    const last = s.lastSeq
    if (last && last.runId === data.run_id) {
      if (data.seq <= last.seq) return { state: s, effects: [] }
      if (data.seq > last.seq + 1) {
        console.warn(`[sse] 事件缺口：期望 ${last.seq + 1}，收到 ${data.seq}（run ${data.run_id}）`)
      }
    }
    s = { ...s, lastSeq: { runId: data.run_id, seq: data.seq } }
  }

  switch (event) {
    case 'agent.started':
      return runReducer(s, { type: 'started', runId: data.run_id, now })
    case 'agent.token':
      return result({ ...s, streamText: s.streamText + (data.text ?? '') })
    case 'agent.reasoning':
      // 推理模型的 chain-of-thought 增量；agent_id 非空时归属子代理（累积到 task 步骤）
      if (data.agent_id) {
        return result({ ...s, tools: appendReasoning(s.tools, data.agent_id, data.text ?? '') })
      }
      return result({ ...s, reasoningText: s.reasoningText + (data.text ?? '') })
    case 'tool.called': {
      // 幂等兜底：双连接窗口内同一调用可能投递两次（单飞订阅已基本防住）
      const callId = data.tool_call_id ?? null
      if (callId && hasStepByCallId(s.tools, callId)) return result(s)
      const step = newStep(`${now}-${s.stepCounter}`, data, now)
      s = { ...s, stepCounter: s.stepCounter + 1 }
      if (!data.agent_id) {
        // 主 agent 调用：把之前流出的正文封为旁白挂到本步骤（与 sidecar 同一条
        // 封段规则，SSE 契约零改动）；正文气泡只剩最终回复（最后未封口段）。
        // 子代理调用不封段（其正文 token 本就不透传，streamText 恒为空）
        step.text = s.streamText
        return result({ ...s, tools: attachStep(s.tools, step, data.agent_id), streamText: '' })
      }
      return result({ ...s, tools: attachStep(s.tools, step, data.agent_id) })
    }
    case 'tool.result':
      return result({ ...s, tools: fillStep(s.tools, data, now) })
    case 'todo.updated':
      return result({
        ...s,
        todos: data.items ?? [],
        done: data.done ?? 0,
        total: data.total ?? 0,
      })
    case 'artifact.created':
      // 产物已落库，刷新列表让 ArtifactCard 即时出现
      return result(s, [{ kind: 'invalidate', queryKey: ['artifacts'] }])
    case 'conversation.renamed':
      // 自动命名已写库（无 seq 连接级事件），刷新会话列表让侧栏标题即时更新
      return result(s, [{ kind: 'invalidate', queryKey: ['conversations'] }])
    case 'run.state': {
      // 连接建立时的对账（sidecar 不补发历史事件）：
      // 在跑则恢复 running（重连/新挂载错过 agent.started），已结束则收敛
      if (data.status === 'running') {
        if (s.terminalRuns.has(data.run_id)) return result(s)
        // 恢复 running 态：计时从恢复时刻重新起算（拿不到真实起点，近似）；
        // 对账事件以 sidecar 权威 run_id 为准（本地旧值可能属于已结束的 run，
        // 保留会让停止钮 POST 到错误的 run）
        return result({
          ...s,
          running: true,
          runId: data.run_id,
          error: null,
          startedAt: s.startedAt ?? now,
        })
      }
      if (data.status === 'waiting_input') {
        // HITL 对账：恢复审批/问答卡并按活卡语义原地冻结（同 settle-interrupt——
        // 断线恰好跨过 run.interrupt 的客户端，工具树/思考/未封口正文同样不清空；
        // pauseNarration 保留既有值，重复对账不抹掉已冻结的旁白）。
        // 半截回复已由 sidecar 落库，拉回消息（活卡存续期间暂停消息不渲染）
        if (s.terminalRuns.has(data.run_id)) return result(s)
        return result(
          {
            ...s,
            running: false,
            stopping: false,
            streamText: '',
            pauseNarration: s.pauseNarration || s.streamText,
            tools: freezeRunningSteps(s.tools),
            interrupt: { runId: data.run_id, requests: data.requests ?? [] },
          },
          [{ kind: 'invalidate-messages' }],
        )
      }
      const err = data.status === 'error' ? (data.error ?? '任务已中断') : null
      return result(
        convergeRun(s, err, data.status === 'error' ? (data.code ?? null) : null),
        // 收敛时拉真值（run 已结束但客户端错过了 completed/error 事件）
        [{ kind: 'invalidate-messages' }],
      )
    }
    case 'run.interrupt':
      // HITL 暂停（additive）：run 转 waiting_input。与 completed 同款时序——
      // 先拉回落库的半截消息（带「等待你的输入…」标记与 trace）再清流式气泡
      return result(s, [
        {
          kind: 'settle-after-messages',
          action: {
            type: 'settle-interrupt',
            runId: data.run_id,
            requests: data.requests ?? [],
          },
        },
      ])
    case 'agent.completed':
      // 流式累积文本与落库内容一致，替换是无缝的（settle 在消息拉回后执行）
      return result(markTerminal(s, data.run_id), [
        { kind: 'settle-after-messages', action: { type: 'settle-completed' } },
      ])
    case 'agent.error':
      return result(markTerminal(s, data.run_id), [
        {
          kind: 'settle-after-messages',
          action: { type: 'settle-error', error: data.error ?? '未知错误', code: data.code ?? null },
        },
      ])
    default:
      return result(s)
  }
}

function markTerminal(s: RunState, runId: string): RunState {
  const terminalRuns = new Set(s.terminalRuns)
  terminalRuns.add(runId)
  return { ...s, terminalRuns }
}
