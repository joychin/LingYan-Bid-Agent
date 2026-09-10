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
  /** 错误分类（agent.error/run.state additive code）：cancelled=用户主动停止，中性呈现；
   *  llm_unavailable=模型服务方过载/超时（ErrorCard 人话文案）、llm_auth=Key 未配置/
   *  失效（附「去设置」）、internal=程序错误（2026-09-08 扩展取值域） */
  errorCode: string | null
  /** LLM 瞬时错误自动重试等待期（agent.retry，2026-09-08 additive）：非空 = 输出区显示
   *  「正在自动重试」shimmer；任何流增量（token/reasoning/tool）到达即清除（流已恢复）。 */
  retrying: { attempt: number; total: number; waitSeconds: number } | null
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
  retrying: null,
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
  /** 过程对账（2026-09-08）：seq 缺口 = SSE 丢过事件（bus 积压丢弃/断连窗口），
   *  拉运行快照把死步/丢步骤补齐；hook 层限频，缺口风暴不会连环拉。 */
  | { kind: 'reconcile-trace'; runId: string }

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
  /** SSE 断线后的 HTTP 对账收敛（getLatestRun 确认已结束才触发）；runId 用于
   *  等待死卡出口的指认（convergeRun 见注释） */
  | { type: 'reconcile-converge'; error: string | null; runId?: string | null }
  /** 流式高频事件（agent.token/agent.reasoning）的合并应用：useRun 把 200ms 窗口内的
   *  增量攒成一次 dispatch——逐 token 应用会让 ChatView 每 token 重渲染（reasoning
   *  还带整棵工具树的递归拷贝）。顺序语义不变：任何其他 action 之前先冲刷缓冲。
   *  seq = 缓冲内最大序号（去重水位续接，无 seq 事件不携带）；seqFrom = 批次首帧
   *  的 seq_from（SSE 微合批 additive）——连续性检查用，见 stream-batch 分支。 */
  | {
      type: 'stream-batch'
      tokens: string
      deltas: Array<{ agentId: string | null; text: string }>
      seq?: { runId: string; seq: number; seqFrom?: number }
    }

export interface ReducerResult {
  state: RunState
  effects: Effect[]
}

/** 收敛已结束的 run：只有处于 running 态时才动作，避免历史 run 的 run.state 反复打扰.
 * 记账字段随 INITIAL_STATE 复位（terminalRuns 也清：与「换会话重挂」语义一致）。
 *  等待死卡出口（2026-09-10 review）：本地冻结的问答卡（running=false 但 interrupt
 *  非空）所属 run 已在服务端终态（别处窗口取消/续跑后终止/sidecar 重启对账）——
 *  对账指认同一 run（runId 匹配）时清卡收敛；指认不上（历史 run）维持原样。 */
function convergeRun(s: RunState, error: string | null, errorCode: string | null = null, runId?: string | null): RunState {
  if (!s.running) {
    if (runId && s.interrupt?.runId === runId) {
      return { ...INITIAL_STATE, lastInstruction: s.lastInstruction, error, errorCode }
    }
    return s
  }
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

/** 断流重试假终态标记（与 sidecar agent._RETRY_RETIRED_ERROR 同文案）：tools 节点
 * 失败的瞬时错误重试会复用同 tool_call_id 真实执行，被标死的步骤允许被覆写/复活。 */
const RETRY_RETIRED_ERROR = 'LLM 流中断，已自动重试'

/** 不可变回填：按 tool_call_id（缺省退化按工具名）找执行中步骤写终态。
 *  paused 也匹配：续跑段 409 双窗口（SSE started 先到、乐观 revive 未发生）下，
 *  冻结步骤收到 tool.result 时服务端它确实在跑——照常回填终态。
 *  断流假终态（error 且文案=重试标记）也匹配且要求 id 相等：tools 节点重试复用
 *  同 id 真实执行，假终态要能被真实结果覆写（按名退化不放开——同工具名多步骤
 *  可能填错步骤）。 */
function fillStep(
  steps: ToolStep[],
  data: { tool?: string; tool_call_id?: string | null; summary?: string; error?: string },
  now: number,
): ToolStep[] {
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]
    const tcid = data.tool_call_id ?? null
    const fillable =
      s.status === 'running' ||
      s.status === 'paused' ||
      (s.status === 'error' && s.error === RETRY_RETIRED_ERROR && !!tcid)
    if (fillable) {
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
/** 断流假终态复活（sidecar agent._revive_step 同口径）：同 tool_call_id 的
 *  tool.called 重发=tools 节点重试复用同 id 真实执行，把标死的步骤复位 running。
 *  只认假终态（error 且文案=标记）——running 的重复投递维持幂等丢弃（引用不变），
 *  done/真实 error 不动（防杂散重复事件拖回运行中）。封段字段（text/reasoning）
 *  保留——它们是第一次调用的产物。 */
function reviveStep(steps: ToolStep[], toolCallId: string, now: number): ToolStep[] {
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i]
    if (s.toolCallId === toolCallId && s.status === 'error' && s.error === RETRY_RETIRED_ERROR) {
      return [
        ...steps.slice(0, i),
        { ...s, status: 'running' as const, error: null, summary: '', endedAt: null, startedAt: now },
        ...steps.slice(i + 1),
      ]
    }
    if (s.children.length > 0) {
      const children = reviveStep(s.children, toolCallId, now)
      if (children !== s.children) {
        return [...steps.slice(0, i), { ...s, children }, ...steps.slice(i + 1)]
      }
    }
  }
  return steps
}

/** 幂等判定：树内是否已有该 tool_call_id 的步骤（双连接窗口去重）。 */
function hasStepByCallId(steps: ToolStep[], toolCallId: string): boolean {
  return steps.some(
    (s) => s.toolCallId === toolCallId || (s.children.length > 0 && hasStepByCallId(s.children, toolCallId)),
  )
}

function stepKey(s: ToolStep): string {
  return s.toolCallId ?? s.id
}

const isFinal = (s: ToolStep) => s.status === 'done' || s.status === 'error'

/** 单步骤合并：本地终态优先（事件已到达=权威，快照必然略旧，防拉取竞态盖回 running）；
 *  本地非终态 + 快照终态 → 采用快照终态（SSE 丢了 tool.result 的死步修复）；
 *  快照 paused 不参与（冻结职责归 run.state waiting_input 对账——续跑乐观 revive
 *  不被旧快照打断）；双方都非终态保留本地（可能带更新的流式痕迹）。
 *  text/reasoning 本地为空时补快照值（丢封段事件场景）。 */
function mergeStep(local: ToolStep, snap: ToolStep): ToolStep {
  const takeSnapFinal = !isFinal(local) && isFinal(snap)
  // 本地 children 为空 = 子代理内部事件全丢（假「启动中」卡）：快照为准
  const children =
    local.children.length === 0 ? snap.children : mergeTraceTree(local.children, snap.children)
  return {
    ...local,
    ...(takeSnapFinal
      ? { status: snap.status, summary: snap.summary, error: snap.error ?? null, endedAt: snap.endedAt ?? null }
      : {}),
    text: local.text || snap.text || '',
    reasoning: local.reasoning || snap.reasoning,
    children,
  }
}

/** 快照对本地树做字段级合并（过程对账，2026-09-08；与 sidecar _merge_trace_trees 同思想）：
 *  以快照顺序为骨架——快照独有的步骤按快照位置补回（丢 tool.called），本地独有的步骤
 *  尾部附加（拉取窗口内新事件创建，事件序单调故必在树尾）。不整树覆盖：拉取窗口内
 *  新到的终态是权威，整树替换会把它盖回 running。 */
function mergeTraceTree(local: ToolStep[], snap: ToolStep[]): ToolStep[] {
  const byKey = new Map(local.map((s) => [stepKey(s), s]))
  const seen = new Set<string>()
  const merged: ToolStep[] = []
  for (const snapStep of snap) {
    const key = stepKey(snapStep)
    const match = byKey.get(key)
    if (match) {
      seen.add(key)
      merged.push(mergeStep(match, snapStep))
    } else {
      merged.push(snapStep)
    }
  }
  for (const s of local) {
    if (!seen.has(stepKey(s))) merged.push(s)
  }
  return merged
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
    case 'sse': {
      const r = reduceSse(s, action)
      // seq 缺口（过程对账触发点之一）：以应用前的水位比对（reduceSse 内部已推进）。
      // 缺口 = bus 积压丢弃或断连窗口丢过事件——可能正是某个 tool.result/子代理事件，
      // 拉运行快照补齐（hook 层限频）。告警保留，缺口从「只告警」变「告警+自愈」。
      // 连续性锚点用 seq_from（SSE 微合批 additive，2026-09-08）：服务端把窗口内
      // 连续增量合并成一帧时 seq 跳号是常态，seq_from==水位+1 即无缺口；旧 sidecar
      // 无此字段退回 seq（跳号=缺口，保守正确）。
      const seq = action.data.seq
      if (typeof seq === 'number') {
        const seqFrom = action.data.seq_from ?? seq
        if (s.lastSeq && s.lastSeq.runId === action.data.run_id && seqFrom > s.lastSeq.seq + 1) {
          console.warn(`[sse] 事件缺口：期望 ${s.lastSeq.seq + 1}，收到 ${seqFrom}（run ${action.data.run_id}）`)
          return { state: r.state, effects: [...r.effects, { kind: 'reconcile-trace', runId: action.data.run_id }] }
        }
      }
      return r
    }
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
        retrying: null,
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
        retrying: null,
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
        retrying: null,
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
      // 清陈旧 error（2026-09-10 修订）：run 健康暂停的转换，send-failed 遗留的红卡
      // 不该陪冻结的问答卡一起显示。
      return result({
        ...s,
        running: false,
        stopping: false,
        streamText: '',
        retrying: null,
        error: null,
        errorCode: null,
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
      // 本地已有过程树 = 不是重建而是过程对账（2026-09-08）：字段级 merge 补死步/丢
      // 步骤，不做 revive/freeze（树空重建才有的恢复语义）、不动 streamText 等流式状态
      const merging = s.tools.length > 0
      const tools = merging
        ? mergeTraceTree(s.tools, action.tools)
        : s.continuation
          ? revivePausedSteps(action.tools)
          : action.status === 'waiting_input'
            ? // 防御性冻结：等待态快照按契约已是 paused 终态树，混入 running 也不转圈
              freezeRunningSteps(action.tools)
            : action.tools
      return result({
        ...s,
        running: action.status === 'running' ? true : s.running,
        runId: action.runId,
        // 快照=running 而 interrupt 残留（跨窗口续跑）时清卡，与 run.state running 对齐
        interrupt: action.status === 'running' ? null : s.interrupt,
        // 清陈旧 error（2026-09-10 修订）：快照=状态重建（活 run 语境），send-failed
        // 遗留的红卡不清会与重建的活卡并存——终态快照已被上方守卫拦下，不会误清
        // settle-error 的真实错误
        error: null,
        errorCode: null,
        tools,
        todos: action.todos,
        // 清单计数随快照重算（丢过 todo.updated 的场景 items 修好了计数不能烂着）
        done: action.todos.filter((t) => t.status === 'completed').length,
        total: action.todos.length,
        // merge 路径不动未封口思考（本地常比快照新——快照 ≥500ms 滞后，回退会在
        // 封段时把思考尾部永久封丢；本地空才采快照值）；树空重建才整段替换
        reasoningText: merging ? s.reasoningText || action.reasoningText : action.reasoningText,
        ...(snapSeq != null ? { lastSeq: { runId: action.runId, seq: snapSeq } } : {}),
      })
    }
    case 'reconcile-converge':
      return result(convergeRun(s, action.error, null, action.runId))
    case 'stream-batch': {
      // 合并窗口的流式增量一次应用（一棵树最多每 agent 走一遍，而非每 token 一遍）
      let tools = s.tools
      let streamText = s.streamText
      let reasoningText = s.reasoningText
      let lastSeq = s.lastSeq
      let changed = false
      const seq = action.seq
      // 流式窗口内的 seq 跳号同样是丢过事件的信号（丢的可能不止 token）——同款对账
      // 触发。连续性锚点用 seqFrom（SSE 微合批 additive，2026-09-08）：批次首帧的
      // seq_from==水位+1 即服务端合并跳号、非缺口；缺 seqFrom（旧 sidecar）退回 seq。
      const seqFrom = seq ? (seq.seqFrom ?? seq.seq) : 0
      const gapEffects: Effect[] =
        seq && s.lastSeq && s.lastSeq.runId === seq.runId && seqFrom > s.lastSeq.seq + 1
          ? [{ kind: 'reconcile-trace', runId: seq.runId }]
          : []
      if (seq && (!lastSeq || lastSeq.runId !== seq.runId || seq.seq > lastSeq.seq)) {
        lastSeq = { runId: seq.runId, seq: seq.seq }
        changed = true
      }
      if (action.tokens) {
        streamText += action.tokens
        changed = true
      }
      for (const d of action.deltas) {
        if (d.agentId) tools = appendReasoning(tools, d.agentId, d.text)
        else reasoningText += d.text
        changed = true
      }
      // 流增量到达 = 重试已成功（流恢复），撤下「正在自动重试」shimmer；仅 seq 推进
      // （无 token/reasoning）不算恢复
      const flowed = !!action.tokens || action.deltas.length > 0
      return changed
        ? result({ ...s, streamText, reasoningText, tools, lastSeq, ...(flowed ? { retrying: null } : {}) }, gapEffects)
        : result(s, gapEffects)
    }
  }
}

function reduceSse(s: RunState, action: Extract<Action, { type: 'sse' }>): ReducerResult {
  const { event, data, now } = action
  // seq 未推进前的原引用：no-op 分支返回它让 setState 同值 bail（避免每条杂项事件
  // 白触发一次 ChatView 整树渲染；代价是这些 seq 水位不前移，最坏多一条缺口对账）
  const orig = s
  // seq 去重（契约 additive 扩展）：双连接残留的重复投递直接丢弃（结构上终结重影）。
  // 缺口检测/告警/对账 effect 统一在 runReducer 的 sse 入口包一层（含 effect 挂载），
  // 这里只管去重与水位推进。无 seq（旧 sidecar/连接级事件）照常接受。
  if (typeof data.seq === 'number') {
    const last = s.lastSeq
    if (last && last.runId === data.run_id) {
      if (data.seq <= last.seq) return { state: s, effects: [] }
    }
    s = { ...s, lastSeq: { runId: data.run_id, seq: data.seq } }
  }

  switch (event) {
    case 'agent.started':
      return runReducer(s, { type: 'started', runId: data.run_id, now })
    case 'agent.token':
      return result({ ...s, streamText: s.streamText + (data.text ?? ''), retrying: null })
    case 'agent.retry':
      // LLM 瞬时错误自动重试等待期（2026-09-08 additive）：清未封口正文（与 sidecar
      // cur_text_parts.clear() 对齐——重试会完整重流出，不清则半截 token 拼重复），
      // 正文气泡区改显示「正在自动重试」shimmer
      return result({
        ...s,
        streamText: '',
        retrying: {
          attempt: data.attempt ?? 1,
          total: data.total ?? 3,
          waitSeconds: data.wait_seconds ?? 0,
        },
      })
    case 'agent.reasoning':
      // 推理模型的 chain-of-thought 增量；agent_id 非空时归属子代理（累积到 task 步骤）
      if (data.agent_id) {
        return result({ ...s, tools: appendReasoning(s.tools, data.agent_id, data.text ?? ''), retrying: null })
      }
      return result({ ...s, reasoningText: s.reasoningText + (data.text ?? ''), retrying: null })
    case 'tool.called': {
      // 幂等兜底：双连接窗口内同一调用可能投递两次（单飞订阅已基本防住）。
      // 例外=断流重试复用同 id 的真实执行：把假终态步骤复活为 running
      //（sidecar _revive_step 同口径），否则重试成功后卡片永久显示「LLM 流中断」。
      const callId = data.tool_call_id ?? null
      if (callId && hasStepByCallId(s.tools, callId)) {
        const revived = reviveStep(s.tools, callId, now)
        return result(revived === s.tools ? orig : { ...s, tools: revived, retrying: null })
      }
      const step = newStep(`${now}-${s.stepCounter}`, data, now)
      s = { ...s, stepCounter: s.stepCounter + 1 }
      if (!data.agent_id) {
        // 主 agent 调用：把之前流出的正文封为旁白、思考流封为本步骤 reasoning 挂到
        // 本步骤（与 sidecar 同一条封段规则，SSE 契约零改动）；正文气泡只剩最终回复
        // （最后未封口段），思考块只剩当前未封口段。子代理调用不封段（其正文 token
        // 本就不透传，streamText 恒为空；reasoning 走 agent_id 归属追加）
        step.text = s.streamText
        step.reasoning = s.reasoningText
        return result({ ...s, tools: attachStep(s.tools, step, data.agent_id), streamText: '', reasoningText: '', retrying: null })
      }
      return result({ ...s, tools: attachStep(s.tools, step, data.agent_id), retrying: null })
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
        if (s.terminalRuns.has(data.run_id)) return result(orig)
        // 恢复 running 态：计时用事件携带的权威起点（runs.created_at，刷新/重连后
        // 续算而非重算），旧 sidecar 无此字段时退回本地值（同 run 重连）再退回当前时刻；
        // 对账事件以 sidecar 权威 run_id 为准（本地旧值可能属于已结束的 run，
        // 保留会让停止钮 POST 到错误的 run）
        return result({
          ...s,
          running: true,
          runId: data.run_id,
          error: null,
          // 跨窗口续跑残留清卡（2026-09-10 review）：本窗口未发起续跑、服务端已被
          // 别处续跑 + 本窗口重连收到 run.state running——冻结的问答卡属已死状态，
          // 残留会让 send 的 HITL 分支抢先判定把新消息当 respond 发出（撞 409）
          interrupt: null,
          startedAt: data.started_at ?? s.startedAt ?? now,
        })
      }
      if (data.status === 'waiting_input') {
        // HITL 对账：恢复审批/问答卡并按活卡语义原地冻结（同 settle-interrupt——
        // 断线恰好跨过 run.interrupt 的客户端，工具树/思考/未封口正文同样不清空；
        // pauseNarration 保留既有值，重复对账不抹掉已冻结的旁白）。
        // 半截回复已由 sidecar 落库，拉回消息（活卡存续期间暂停消息不渲染）
        if (s.terminalRuns.has(data.run_id)) return result(orig)
        return result(
          {
            ...s,
            running: false,
            stopping: false,
            streamText: '',
            pauseNarration: s.pauseNarration || s.streamText,
            tools: freezeRunningSteps(s.tools),
            interrupt: { runId: data.run_id, requests: data.requests ?? [] },
            // 与 running 分支对齐清陈旧 error（2026-09-10 修订）：重连恢复等待卡时
            // send-failed 遗留的红卡同样过期
            error: null,
            errorCode: null,
          },
          [{ kind: 'invalidate-messages' }],
        )
      }
      const err = data.status === 'error' ? (data.error ?? '任务已中断') : null
      return result(
        convergeRun(s, err, data.status === 'error' ? (data.code ?? null) : null, data.run_id),
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
        // run 期间模型可能新写了工作台文件（body/ 指引与正文），结束时刷新面板列表
        { kind: 'invalidate', queryKey: ['workbench'] },
      ])
    case 'agent.error':
      return result(markTerminal(s, data.run_id), [
        {
          kind: 'settle-after-messages',
          action: { type: 'settle-error', error: data.error ?? '未知错误', code: data.code ?? null },
        },
        { kind: 'invalidate', queryKey: ['workbench'] },
      ])
    default:
      return result(orig)
  }
}

function markTerminal(s: RunState, runId: string): RunState {
  const terminalRuns = new Set(s.terminalRuns)
  terminalRuns.add(runId)
  return { ...s, terminalRuns }
}
