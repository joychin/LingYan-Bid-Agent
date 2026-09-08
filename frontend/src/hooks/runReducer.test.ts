/**
 * runReducer 事件回放测试：fixture 驱动整条 SSE 事件管线（固定时钟，纯函数）。
 * 与 sidecar tests/test_contract.py 的同场景断言构成「封段规则双语言 parity」——
 * 两侧任何一边改了 tool.called 封段语义，对应测试需要同步修改。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentEventData, ToolStep } from '@/api/sse'
import { INITIAL_STATE, runReducer, type Action, type Effect, type RunState } from './runReducer'

// JSON 字面量推断类型与契约联合（literal status / null 宽窄）不完全对齐，回放侧整体断言转换
import normalJson from './__fixtures__/scenario-normal.json'
import subagentJson from './__fixtures__/scenario-subagent.json'
import hitlJson from './__fixtures__/scenario-hitl.json'
import cancelJson from './__fixtures__/scenario-cancel.json'
import seqJson from './__fixtures__/scenario-seq.json'

const normal = { events: normalJson.events as unknown as FixtureEvent[] }
const subagent = { events: subagentJson.events as unknown as FixtureEvent[] }
const hitl = { events: hitlJson.events as unknown as FixtureEvent[] }
const cancel = { events: cancelJson.events as unknown as FixtureEvent[] }
const seq = { events: seqJson.events as unknown as FixtureEvent[] }

const NOW = 1_700_000_000_000

interface FixtureEvent {
  event: string
  data: AgentEventData
}

function replay(events: FixtureEvent[], extra: Action[] = []) {
  let state: RunState = INITIAL_STATE
  const effects: Effect[] = []
  const apply = (a: Action) => {
    const r = runReducer(state, a)
    state = r.state
    effects.push(...r.effects)
  }
  for (const e of events) apply({ type: 'sse', event: e.event, data: e.data, now: NOW })
  for (const a of extra) apply(a)
  return { state, effects }
}

const settleActionsFor = (effects: Effect[]): Action[] =>
  effects.flatMap((e) => (e.kind === 'settle-after-messages' ? [e.action] : []))

describe('正常 run', () => {
  it('旁白/思考封段：tool.called 把之前正文封为 step.text、思考封为 step.reasoning 并清空', () => {
    const { state, effects } = replay(normal.events)
    expect(state.tools).toHaveLength(1)
    expect(state.tools[0].text).toBe('我先查一下资料。') // 旁白挂到工具步骤
    expect(state.tools[0].reasoning).toBe('想想') // 思考流挂到工具步骤（时序流水）
    expect(state.tools[0].status).toBe('done')
    expect(state.streamText).toBe('完成了：X。') // 最后未封口段 = 最终回复
    expect(state.reasoningText).toBe('') // 未封口思考已全部封段
    expect(state.todos).toHaveLength(2)
    expect(state.running).toBe(true) // completed 的收敛在 settle（消息拉回后）
    expect(effects).toContainEqual({ kind: 'invalidate', queryKey: ['artifacts'] })
  })

  it('settle-completed 撤掉流式气泡，保留最终收敛语义', () => {
    const { state } = replay(normal.events, settleActionsFor(replay(normal.events).effects))
    expect(state.running).toBe(false)
    expect(state.streamText).toBe('')
    expect(state.reasoningText).toBe('')
    expect(state.error).toBeNull()
  })

  it('最终回复前的思考留在未封口段：底部思考块只显示当前段', () => {
    let s = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'agent.reasoning',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '第一段思考', agent_id: null },
    }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'ls', args: {}, tool_call_id: 't1', agent_id: null },
    }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'agent.reasoning',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '最终回复前的思考', agent_id: null },
    }).state
    expect(s.tools[0].reasoning).toBe('第一段思考')
    expect(s.reasoningText).toBe('最终回复前的思考')
  })
})

describe('子代理树', () => {
  it('agent_id 归属 children，子代理 reasoning 累积到 task 步骤', () => {
    const { state } = replay(subagent.events)
    const task = state.tools[0]
    expect(task.tool).toBe('task')
    expect(task.text).toBe('派个帮手去查。') // 主 agent 的 task 调用同样封段
    expect(task.status).toBe('done')
    expect(task.reasoning).toBe('子思考') // 子代理 reasoning 累积到所属 task 步骤（非 child）
    expect(task.children).toHaveLength(1)
    expect(task.children[0].toolCallId).toBe('child_1')
    expect(task.children[0].status).toBe('done')
  })
})

describe('HITL 中断与续跑', () => {
  it('run.interrupt → settle-interrupt 恢复裁决卡；续段 agent.started 续接同 run', () => {
    const first = replay(hitl.events.slice(0, 3))
    const settles = settleActionsFor(first.effects)
    expect(settles).toHaveLength(1)
    expect(settles[0]).toMatchObject({ type: 'settle-interrupt' })

    const { state } = replay(hitl.events.slice(0, 3), settles)
    expect(state.running).toBe(false)
    expect(state.interrupt).toMatchObject({ runId: 'r1' })
    expect(state.interrupt?.requests[0].tool).toBe('ask_human')

    // 用户 respond 后乐观置 running（hook 的 dispatch('started')），随后真 agent.started(seq4) 到达；
    // 全部按真实时序作为 action 序列回放（事件 → settle → started → 续段事件）
    const resumed = replay([], [
      { type: 'sse', event: hitl.events[0].event, data: hitl.events[0].data, now: NOW },
      { type: 'sse', event: hitl.events[1].event, data: hitl.events[1].data, now: NOW },
      { type: 'sse', event: hitl.events[2].event, data: hitl.events[2].data, now: NOW },
      ...settles,
      { type: 'started', runId: 'r1', now: NOW },
      { type: 'sse', event: hitl.events[3].event, data: hitl.events[3].data, now: NOW },
    ])
    expect(resumed.state.running).toBe(true)
    expect(resumed.state.interrupt).toBeNull()
  })

  it('纯审批续跑保留暂停的 task 卡，并将其恢复为运行态', () => {
    const started = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    const withTask = runReducer(started, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: {
        run_id: 'r1',
        conversation_id: 'c1',
        tool: 'task',
        args: { description: '检索中石化招标', subagent_type: 'general-purpose' },
        tool_call_id: 'task_1',
      },
    }).state
    const withTodos = runReducer(withTask, {
      type: 'sse',
      event: 'todo.updated',
      now: NOW,
      data: {
        run_id: 'r1',
        conversation_id: 'c1',
        done: 0,
        total: 1,
        items: [{ content: '检索', status: 'in_progress' }],
      },
    }).state
    const withReasoning = runReducer(withTodos, {
      type: 'sse',
      event: 'agent.reasoning',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '先想一步' },
    }).state
    const paused = runReducer(withReasoning, {
      type: 'settle-interrupt',
      runId: 'r1',
      requests: [{ tool: 'task', args: {}, description: '确认派发', allowed: ['approve', 'reject'] }],
    }).state
    // 活卡原地冻结：running 步骤转 paused（卡片呈现「等待确认/已暂停」，不转圈）
    expect(paused.tools[0].status).toBe('paused')
    // 冻结不清空：思考流保留（续跑追加），todos 记账保留
    expect(paused.reasoningText).toBe('先想一步')
    expect(paused.todos).toEqual([{ content: '检索', status: 'in_progress' }])

    const resumed = runReducer(paused, { type: 'started', runId: 'r1', now: NOW, continuation: true }).state
    expect(resumed.tools).toHaveLength(1)
    expect(resumed.tools[0].tool).toBe('task')
    expect(resumed.tools[0].status).toBe('running')
    expect(resumed.continuation).toBe(true)
    // 同 run started 幂等：暂停冻结的内容全部跨续跑保留
    expect(resumed.reasoningText).toBe('先想一步')
    expect(resumed.done).toBe(0)
    expect(resumed.total).toBe(1)
  })

  it('settle-interrupt 原地冻结：未封口正文转暂停旁白，running 步骤（含子级）转 paused', () => {
    let s = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'agent.token',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '先派帮手。' },
    }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'task', args: {}, tool_call_id: 't1' },
    }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'fetch_url', args: {}, tool_call_id: 'c2', agent_id: 't1' },
    }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'agent.token',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '有个问题要问你' },
    }).state
    const paused = runReducer(s, {
      type: 'settle-interrupt',
      runId: 'r1',
      requests: [{ tool: 'ask_human', args: {}, description: '问一句', allowed: ['respond'] }],
    }).state
    // 未封口正文不消失：streamText 移入 pauseNarration（活卡冻结期间渲染为旁白行）
    expect(paused.streamText).toBe('')
    expect(paused.pauseNarration).toBe('有个问题要问你')
    // 树保留：封段旁白仍在步骤上，running 步骤（含子代理 children）冻结为 paused
    expect(paused.tools[0].status).toBe('paused')
    expect(paused.tools[0].text).toBe('先派帮手。')
    expect(paused.tools[0].children[0].status).toBe('paused')

    // 续跑段 409 双窗口兜底（SSE started 先到、乐观 revive 未发生）：冻结步骤
    // 收到 tool.result 照常回填终态（服务端它确实在跑）
    const healed = runReducer(paused, {
      type: 'sse',
      event: 'tool.result',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'task', tool_call_id: 't1', summary: '完成' },
    }).state
    expect(healed.tools[0].status).toBe('done')
  })

  it('普通指令与 HITL 回答分开记账：纯 approve 不产生回答文本', () => {
    const sent = runReducer(INITIAL_STATE, { type: 'remember-instruction', text: '原始任务指令' }).state
    expect(sent.lastInstruction).toBe('原始任务指令')
    expect(sent.continuationAnswer).toBe('')

    const approved = runReducer(sent, { type: 'started', runId: 'r1', now: NOW, continuation: true }).state
    expect(approved.continuationAnswer).toBe('')

    const answered = runReducer(approved, { type: 'remember-answer', text: '方案 A' }).state
    expect(answered.continuationAnswer).toBe('方案 A')
    const nextInstruction = runReducer(answered, { type: 'remember-instruction', text: '继续整理' }).state
    expect(nextInstruction.lastInstruction).toBe('继续整理')
    expect(nextInstruction.continuationAnswer).toBe('')
  })

  it('续段 seq 续接：重放旧事件被丢弃，不重复计入正文', () => {
    // 模拟双连接窗口：完整跑完后又收到一条历史 seq=2 的重复 token
    const dup: FixtureEvent = {
      event: 'agent.token',
      data: { run_id: 'r1', conversation_id: 'c1', text: '有个问题要问你', seq: 2 },
    }
    const base = replay(hitl.events, settleActionsFor(replay(hitl.events).effects))
    const r = runReducer(base.state, { type: 'sse', ...dup, now: NOW })
    expect(r.state.streamText).toBe(base.state.streamText) // 未受重复事件影响
  })

  it('run.state waiting_input 对账：活卡原地冻结（断线跨过 run.interrupt 的客户端）', () => {
    let s = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'ls', args: {}, tool_call_id: 'c1' },
    }).state
    s = runReducer(s, {
      type: 'sse',
      event: 'agent.token',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '有个问题要问你' },
    }).state
    const r = runReducer(s, {
      type: 'sse',
      event: 'run.state',
      now: NOW,
      data: {
        run_id: 'r1',
        conversation_id: 'c1',
        status: 'waiting_input',
        requests: [{ tool: 'ask_human', args: {}, description: '问一句', allowed: ['respond'] }],
      },
    })
    expect(r.state.running).toBe(false)
    expect(r.state.interrupt).toMatchObject({ runId: 'r1' })
    expect(r.state.pauseNarration).toBe('有个问题要问你')
    expect(r.state.tools[0].status).toBe('paused')
    expect(r.effects).toContainEqual({ kind: 'invalidate-messages' })

    // 等待期 SSE 重连的重复对账：不抹掉已冻结的旁白、不重复冻结出问题
    const again = runReducer(r.state, {
      type: 'sse',
      event: 'run.state',
      now: NOW,
      data: {
        run_id: 'r1',
        conversation_id: 'c1',
        status: 'waiting_input',
        requests: [{ tool: 'ask_human', args: {}, description: '问一句', allowed: ['respond'] }],
      },
    }).state
    expect(again.pauseNarration).toBe('有个问题要问你')
    expect(again.tools[0].status).toBe('paused')
  })

  it('run.state running 对账：started_at 权威起点续算（刷新/重连后计时不重算）', () => {
    // 刷新/切会话后 RunState 复位：对账事件携带 runs.created_at 换算的权威起点
    const r = runReducer(INITIAL_STATE, {
      type: 'sse',
      event: 'run.state',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', status: 'running', started_at: NOW - 60_000 },
    })
    expect(r.state.running).toBe(true)
    expect(r.state.startedAt).toBe(NOW - 60_000)

    // 旧 sidecar 无 started_at：退回本地值（同 run 重连保留既有起点），再退回当前时刻
    const reconnected = runReducer(r.state, {
      type: 'sse',
      event: 'run.state',
      now: NOW + 5_000,
      data: { run_id: 'r1', conversation_id: 'c1', status: 'running' },
    })
    expect(reconnected.state.startedAt).toBe(NOW - 60_000)
    const legacy = runReducer(INITIAL_STATE, {
      type: 'sse',
      event: 'run.state',
      now: NOW,
      data: { run_id: 'r2', conversation_id: 'c1', status: 'running' },
    })
    expect(legacy.state.startedAt).toBe(NOW)
  })

  it('continuation sticky：续跑乐观置位后，SSE agent.started 二次到达不冲掉；settle 复位', () => {
    const first = replay(hitl.events.slice(0, 3))
    const settles = settleActionsFor(first.effects)
    // settle-interrupt 后 decide/respond 乐观 started(continuation) → 真 agent.started 到达
    const resumed = replay(hitl.events.slice(0, 3), [
      ...settles,
      { type: 'started', runId: 'r1', now: NOW, continuation: true },
      { type: 'sse', event: hitl.events[3].event, data: hitl.events[3].data, now: NOW },
    ])
    expect(resumed.state.continuation).toBe(true)
    expect(resumed.state.running).toBe(true)

    // 续段完成：settle-completed 复位（下一段不再是续跑）
    const doneEffects = [
      { kind: 'settle-after-messages', action: { type: 'settle-completed' } } as Effect,
    ]
    const after = runReducer(resumed.state, settleActionsFor(doneEffects)[0]).state
    expect(after.running).toBe(false)
    expect(after.continuation).toBe(false)

    // 普通 run 的 started（无标记、state 里也无残留）不置 continuation
    const fresh = runReducer(INITIAL_STATE, { type: 'started', runId: 'r2', now: NOW }).state
    expect(fresh.continuation).toBe(false)
  })
})

describe('运行快照对账', () => {
  const taskStep = {
    id: 's1',
    tool: 'task',
    args: { description: '检索中石化招标' },
    status: 'running' as const,
    summary: '',
    toolCallId: 't1',
    reasoning: '',
    children: [],
    startedAt: NOW,
    endedAt: null,
  }

  it('断线重挂：快照恢复 running task 卡并推进 seq 游标', () => {
    const restored = runReducer(INITIAL_STATE, {
      type: 'snapshot',
      runId: 'r1',
      status: 'running',
      tools: [taskStep],
      todos: [],
      reasoningText: '主代理思考',
      snapshotSeq: 42,
    }).state
    expect(restored.running).toBe(true)
    expect(restored.runId).toBe('r1')
    expect(restored.tools).toHaveLength(1)
    expect(restored.tools[0].status).toBe('running')
    expect(restored.reasoningText).toBe('主代理思考')
    expect(restored.lastSeq).toEqual({ runId: 'r1', seq: 42 })

    // 快照 seq 之后的实时事件正常接受，之前的重复被丢弃
    const after = runReducer(restored, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'fetch_url', args: { url: 'https://x' }, tool_call_id: 'c2', agent_id: 't1', seq: 43 },
    }).state
    expect(after.tools[0].children).toHaveLength(1)
    // 快照 seq 晚于实时事件到达：lastSeq 取 max 不回退
    const live = runReducer(restored, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'ls', args: { path: '/' }, tool_call_id: 'c9', seq: 50 },
    }).state
    const stale = runReducer(live, {
      type: 'snapshot',
      runId: 'r1',
      status: 'running',
      tools: [taskStep],
      todos: [],
      reasoningText: '',
      snapshotSeq: 42,
    }).state
    expect(stale.lastSeq).toEqual({ runId: 'r1', seq: 50 })
  })

  it('waiting_input 快照：恢复冻结树与思考但不置 running（等待期刷新/重连重建活卡）', () => {
    const restored = runReducer(INITIAL_STATE, {
      type: 'snapshot',
      runId: 'r1',
      status: 'waiting_input',
      tools: [{ ...taskStep, status: 'paused' as const }],
      todos: [],
      reasoningText: '暂停前的思考',
    }).state
    expect(restored.running).toBe(false)
    expect(restored.runId).toBe('r1')
    expect(restored.tools[0].status).toBe('paused')
    expect(restored.reasoningText).toBe('暂停前的思考')

    // 防御性冻结：等待态快照混入 running 步骤也转 paused（不转圈）
    const defensive = runReducer(INITIAL_STATE, {
      type: 'snapshot',
      runId: 'r1',
      status: 'waiting_input',
      tools: [taskStep],
      todos: [],
      reasoningText: '',
    }).state
    expect(defensive.running).toBe(false)
    expect(defensive.tools[0].status).toBe('paused')
  })

  it('已终态或已切走的 run 不被旧快照复活/覆盖', () => {
    const terminal = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    const marked = { ...terminal, terminalRuns: new Set(['r1']) }
    const revived = runReducer(marked, {
      type: 'snapshot',
      runId: 'r1',
      status: 'running',
      tools: [taskStep],
      todos: [],
      reasoningText: '',
    }).state
    expect(revived.tools).toHaveLength(0)

    // 已切到 r2 的会话：r1 的迟到快照不覆盖当前 run
    const switched = { ...INITIAL_STATE, runId: 'r2' }
    const kept = runReducer(switched, {
      type: 'snapshot',
      runId: 'r1',
      status: 'running',
      tools: [taskStep],
      todos: [],
      reasoningText: '',
    }).state
    expect(kept.runId).toBe('r2')
  })
})

describe('用户停止', () => {
  it('code=cancelled 中性收敛；terminalRuns 挡住过期 run.state 复活', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const first = replay(cancel.events.slice(0, 3))
    expect(first.state.running).toBe(true) // settle 前仍是 running
    const settles = settleActionsFor(first.effects)

    const { state } = replay(cancel.events.slice(0, 3), settles)
    expect(state.running).toBe(false)
    expect(state.stopping).toBe(false)
    expect(state.error).toBe('任务已停止')
    expect(state.errorCode).toBe('cancelled')
    expect(state.terminalRuns.has('r1')).toBe(true)

    // settle 之后再收到同 run 的过期 running 对账事件（terminalRuns 已含 → 不复活）
    // 与连接级 conversation.renamed（无 seq，照常处理）
    const after = replay(cancel.events.slice(0, 3), [
      ...settles,
      { type: 'sse', event: 'run.state', data: cancel.events[3].data, now: NOW },
      { type: 'sse', event: 'conversation.renamed', data: cancel.events[4].data, now: NOW },
    ])
    expect(after.state.running).toBe(false)
    expect(after.effects).toContainEqual({ kind: 'invalidate', queryKey: ['conversations'] })
    warn.mockRestore()
  })
})

describe('seq 去重与缺口', () => {
  let warn: ReturnType<typeof vi.spyOn>
  beforeEach(() => {
    warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })
  afterEach(() => warn.mockRestore())

  it('缺口告警一次、重复丢弃、换 run 重新起算', () => {
    const { state } = replay(seq.events)
    // seq2 缺口告警一次；seq5 重复丢弃（正文只有一份 A）
    expect(state.streamText).toBe('AB新run不受旧seq限制')
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0][0])).toContain('事件缺口')
    expect(state.lastSeq).toEqual({ runId: 'r2', seq: 2 })
  })

  it('seq 缺口发出过程对账 effect（告警+自愈，2026-09-08）', () => {
    const { effects } = replay(seq.events)
    // seq 1 → 5 的缺口恰好在 r1 上发生一次；重复（5）、连续（6）、换 run（r2:2）不触发
    expect(effects).toContainEqual({ kind: 'reconcile-trace', runId: 'r1' })
    expect(effects.filter((e) => e.kind === 'reconcile-trace')).toHaveLength(1)
  })

  it('stream-batch 的 seq 跳号同样触发过程对账（丢的可能不止 token）', () => {
    const started = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    const withSeq = runReducer(started, {
      type: 'stream-batch',
      tokens: 'x',
      deltas: [],
      seq: { runId: 'r1', seq: 3 },
    }).state
    expect(withSeq.lastSeq).toEqual({ runId: 'r1', seq: 3 })
    const gap = runReducer(withSeq, {
      type: 'stream-batch',
      tokens: 'y',
      deltas: [],
      seq: { runId: 'r1', seq: 8 },
    })
    expect(gap.effects).toContainEqual({ kind: 'reconcile-trace', runId: 'r1' })
    const continuous = runReducer(withSeq, {
      type: 'stream-batch',
      tokens: 'z',
      deltas: [],
      seq: { runId: 'r1', seq: 4 },
    })
    expect(continuous.effects.filter((e) => e.kind === 'reconcile-trace')).toHaveLength(0)
  })

  it('合批帧 seq_from 连续不触发对账，真缺口仍触发（SSE 微合批 2026-09-08）', () => {
    const started = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    // 水位 null → 首帧跳号不算缺口；单帧带 seq_from（侧未合并也带）
    const s1 = runReducer(started, {
      type: 'sse',
      event: 'agent.token',
      data: { run_id: 'r1', conversation_id: 'c1', text: 'x', seq: 3, seq_from: 1 },
      now: NOW,
    })
    expect(s1.state.streamText).toBe('x')
    expect(s1.state.lastSeq).toEqual({ runId: 'r1', seq: 3 })
    expect(s1.effects.filter((e) => e.kind === 'reconcile-trace')).toHaveLength(0)
    expect(warn).not.toHaveBeenCalled()
    // 服务端合并跳号（seq 3→6 但 seq_from=4 连续）→ 不告警不对账
    const s2 = runReducer(s1.state, {
      type: 'sse',
      event: 'agent.token',
      data: { run_id: 'r1', conversation_id: 'c1', text: 'y', seq: 6, seq_from: 4 },
      now: NOW,
    })
    expect(s2.state.lastSeq).toEqual({ runId: 'r1', seq: 6 })
    expect(s2.effects.filter((e) => e.kind === 'reconcile-trace')).toHaveLength(0)
    expect(warn).not.toHaveBeenCalled()
    // 真缺口（seq_from=9 > 水位+1）→ 告警+对账
    const s3 = runReducer(s2.state, {
      type: 'sse',
      event: 'agent.token',
      data: { run_id: 'r1', conversation_id: 'c1', text: 'z', seq: 12, seq_from: 9 },
      now: NOW,
    })
    expect(s3.effects).toContainEqual({ kind: 'reconcile-trace', runId: 'r1' })
    expect(warn).toHaveBeenCalledTimes(1)
    expect(String(warn.mock.calls[0][0])).toContain('事件缺口')
  })

  it('stream-batch 携带 seqFrom 时合并跳号不对账、真缺口对账', () => {
    const started = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    const withSeq = runReducer(started, {
      type: 'stream-batch',
      tokens: 'x',
      deltas: [],
      seq: { runId: 'r1', seq: 3, seqFrom: 1 },
    }).state
    expect(withSeq.lastSeq).toEqual({ runId: 'r1', seq: 3 })
    // 合并跳号 3→8、seqFrom=4 连续 → 不对账，水位推进
    const merged = runReducer(withSeq, {
      type: 'stream-batch',
      tokens: 'y',
      deltas: [],
      seq: { runId: 'r1', seq: 8, seqFrom: 4 },
    })
    expect(merged.effects.filter((e) => e.kind === 'reconcile-trace')).toHaveLength(0)
    expect(merged.state.lastSeq).toEqual({ runId: 'r1', seq: 8 })
    // 真缺口 seqFrom=10 → 对账
    const gap = runReducer(merged.state, {
      type: 'stream-batch',
      tokens: 'z',
      deltas: [],
      seq: { runId: 'r1', seq: 12, seqFrom: 10 },
    })
    expect(gap.effects).toContainEqual({ kind: 'reconcile-trace', runId: 'r1' })
  })
})

describe('过程对账 merge（树非空时快照补死步/丢步骤，2026-09-08）', () => {
  const baseStep = (id: string, tool: string, over: Partial<ToolStep> = {}): ToolStep => ({
    id,
    tool,
    args: { description: `节-${id}` },
    status: 'running',
    summary: '',
    error: null,
    toolCallId: id,
    reasoning: '',
    text: '',
    children: [],
    startedAt: NOW,
    endedAt: null,
    ...over,
  })
  const task = (id: string, over: Partial<ToolStep> = {}): ToolStep => baseStep(id, 'task', over)
  const grep = (id: string, over: Partial<ToolStep> = {}): ToolStep => baseStep(id, 'grep', over)

  /** 前置：running 态 + 已有部分树（8 路子代理并发场景的活卡） */
  const liveWith = (tools: ToolStep[], over: Partial<RunState> = {}): RunState => ({
    ...INITIAL_STATE,
    running: true,
    runId: 'r1',
    lastSeq: { runId: 'r1', seq: 10 },
    streamText: '正在流出',
    tools,
    ...over,
  })

  const snapInto = (
    s: RunState,
    tools: ToolStep[],
    over: Partial<Extract<Action, { type: 'snapshot' }>> = {},
  ) =>
    runReducer(s, {
      type: 'snapshot',
      runId: 'r1',
      status: 'running',
      tools,
      todos: [],
      reasoningText: '',
      ...over,
    }).state

  it('死步修复：本地 running（丢 tool.result）+ 快照终态 → 采用快照终态', () => {
    const s = snapInto(liveWith([task('t1')]), [
      task('t1', { status: 'done', summary: '已写入 低代码产品方案.docx', endedAt: NOW + 9000 }),
    ])
    expect(s.tools[0].status).toBe('done')
    expect(s.tools[0].summary).toBe('已写入 低代码产品方案.docx')
    expect(s.tools[0].endedAt).toBe(NOW + 9000)
    // merge 不动流式状态（快照没有未封口正文）
    expect(s.streamText).toBe('正在流出')
  })

  it('拉取竞态防护：本地终态不被略旧的快照盖回 running', () => {
    const s = snapInto(liveWith([grep('g1', { status: 'done', summary: '命中 3' })]), [
      grep('g1', { status: 'running' }),
    ])
    expect(s.tools[0].status).toBe('done')
    expect(s.tools[0].summary).toBe('命中 3')
  })

  it('快照 paused 不覆盖本地 running（冻结职责在 run.state 对账，续跑 revive 不被打断）', () => {
    const s = snapInto(liveWith([task('t1')]), [task('t1', { status: 'paused' })])
    expect(s.tools[0].status).toBe('running')
  })

  it('假「启动中」卡修复：本地 task 零 children（内部事件全丢）→ 采用快照 children', () => {
    const childDone = grep('c1', { status: 'done', summary: '读视图' })
    const childFixed = grep('c2', { status: 'done', summary: '写入节文件' })
    const s = snapInto(liveWith([task('t1')]), [task('t1', { children: [childDone, childFixed] })])
    expect(s.tools[0].children).toHaveLength(2)
    // 本地 children 为空整棵采用（含其中终态）
    expect(s.tools[0].children[0].status).toBe('done')
    expect(s.tools[0].children[1].summary).toBe('写入节文件')
  })

  it('丢 tool.called 的步骤按快照位置补回；拉取窗口内新建的本地步骤尾部附加', () => {
    const s = snapInto(liveWith([grep('a', { status: 'done' }), task('t1'), task('t2')]), [
      grep('a', { status: 'done' }),
      grep('b', { status: 'done', summary: '丢过 tool.called 的步骤' }),
      task('t1', { status: 'done', summary: '已完成' }),
    ])
    expect(s.tools.map((t) => t.toolCallId)).toEqual(['a', 'b', 't1', 't2'])
    expect(s.tools[1].summary).toBe('丢过 tool.called 的步骤')
    expect(s.tools[2].status).toBe('done')
    expect(s.tools[3].status).toBe('running')
  })

  it('封段字段本地缺失时补快照值；本地有值则保留', () => {
    const s = snapInto(
      liveWith([
        grep('a', { status: 'running', text: '', reasoning: '' }),
        grep('b', { status: 'running', text: '本地旁白', reasoning: '本地思考' }),
      ]),
      [
        grep('a', { text: '快照旁白', reasoning: '快照思考' }),
        grep('b', { text: '快照旁白', reasoning: '快照思考' }),
      ],
    )
    expect(s.tools[0].text).toBe('快照旁白')
    expect(s.tools[0].reasoning).toBe('快照思考')
    expect(s.tools[1].text).toBe('本地旁白')
    expect(s.tools[1].reasoning).toBe('本地思考')
  })

  it('todos 与计数随快照重算（「任务清单 0/0」同源修复）', () => {
    const s = snapInto(liveWith([task('t1')], { todos: [], done: 0, total: 0 }), [], {
      todos: [
        { content: '解析', status: 'completed' as const },
        { content: '目录', status: 'completed' as const },
        { content: '正文', status: 'in_progress' as const },
      ],
    })
    expect(s.todos).toHaveLength(3)
    expect(s.done).toBe(2)
    expect(s.total).toBe(3)
  })

  it('merge 路径同样受终态守卫：已终态的 run 不被快照复活', () => {
    const marked = liveWith([task('t1')], { running: false, terminalRuns: new Set(['r1']) })
    const s = snapInto(marked, [task('t1', { status: 'done' })])
    expect(s).toBe(marked) // 原引用 bail：守卫命中直接返回
  })
})

describe('agent.retry（LLM 自动重试可见，2026-09-08 契约 additive）', () => {
  it('agent.retry 清未封口正文并置 retrying；流恢复即清除；settle-error 不残留', () => {
    const started = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    // 半截正文已流出 → 自动重试到达（sidecar cur_text_parts.clear() 的前端镜像）
    const s1 = runReducer(started, {
      type: 'sse',
      event: 'agent.token',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '半截', seq: 2 },
    }).state
    const s2 = runReducer(s1, {
      type: 'sse',
      event: 'agent.retry',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', attempt: 1, total: 3, wait_seconds: 3, seq: 3 },
    }).state
    expect(s2.retrying).toEqual({ attempt: 1, total: 3, waitSeconds: 3 })
    expect(s2.streamText).toBe('') // 重试完整重流出，半截 token 不拼重复
    // 重试成功：流恢复，token 继续到达 → shimmer 撤下
    const s3 = runReducer(s2, {
      type: 'sse',
      event: 'agent.token',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', text: '重流出的正文', seq: 4 },
    }).state
    expect(s3.retrying).toBeNull()
    expect(s3.streamText).toBe('重流出的正文')
    // 重试耗尽 → settle-error（code=llm_unavailable）不残留 retrying
    const s4 = runReducer(s3, {
      type: 'sse',
      event: 'agent.retry',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', attempt: 3, total: 3, wait_seconds: 30, seq: 5 },
    }).state
    const settled = runReducer(s4, {
      type: 'settle-error',
      error: '模型服务暂时不可用，已自动重试 3 次仍失败。\n服务方返回：overloaded',
      code: 'llm_unavailable',
    }).state
    expect(settled.retrying).toBeNull()
    expect(settled.errorCode).toBe('llm_unavailable')
  })

  it('stream-batch 流增量清除 retrying；仅 seq 推进（无 token/思考）不清除', () => {
    const started = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
    const s1 = runReducer(started, {
      type: 'sse',
      event: 'agent.retry',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', attempt: 2, total: 3, wait_seconds: 10, seq: 3 },
    }).state
    const s2 = runReducer(s1, { type: 'stream-batch', tokens: '', deltas: [], seq: { runId: 'r1', seq: 4 } }).state
    expect(s2.retrying).not.toBeNull() // 纯 seq 推进不是流恢复
    const s3 = runReducer(s2, { type: 'stream-batch', tokens: '正文', deltas: [], seq: { runId: 'r1', seq: 5 } }).state
    expect(s3.retrying).toBeNull()
  })
})

describe('stream-batch（流式高频事件合并应用）', () => {
  const started = runReducer(INITIAL_STATE, { type: 'started', runId: 'r1', now: NOW }).state
  const taskCall: Action = {
    type: 'sse',
    event: 'tool.called',
    now: NOW,
    data: { run_id: 'r1', conversation_id: 'c1', tool: 'task', args: { description: '写第一册' }, tool_call_id: 't1', agent_id: null },
  }

  it('token 与主/子代理思考增量合并应用；seq 续接去重水位', () => {
    const s0 = runReducer(started, taskCall).state
    const { state } = runReducer(s0, {
      type: 'stream-batch',
      tokens: '正文A',
      deltas: [
        { agentId: null, text: '主思考' },
        { agentId: 't1', text: '子思考1' },
        { agentId: 't1', text: '子思考2' },
      ],
      seq: { runId: 'r1', seq: 9 },
    })
    expect(state.streamText).toBe('正文A')
    expect(state.reasoningText).toBe('主思考')
    const task = state.tools.find((t) => t.tool === 'task')
    expect(task?.reasoning).toBe('子思考1子思考2')
    expect(state.lastSeq).toEqual({ runId: 'r1', seq: 9 })
  })

  it('batch 后紧跟 tool.called：封段语义与逐 token 应用一致（缓冲先落地）', () => {
    const s0 = runReducer(started, {
      type: 'stream-batch',
      tokens: '我先查资料。',
      deltas: [{ agentId: null, text: '想想' }],
      seq: { runId: 'r1', seq: 3 },
    }).state
    const s1 = runReducer(s0, {
      type: 'sse',
      event: 'tool.called',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', tool: 'grep', args: {}, tool_call_id: 'g1', agent_id: null },
    }).state
    expect(s1.tools[0].text).toBe('我先查资料。')
    expect(s1.tools[0].reasoning).toBe('想想')
    expect(s1.streamText).toBe('')
  })

  it('空增量不换 state 引用（setState 同值 bail 生效）', () => {
    const r = runReducer(started, { type: 'stream-batch', tokens: '', deltas: [] })
    expect(r.state).toBe(started)
  })

  it('seq 不回退：旧 seq 的 batch 只应用文本不拉低水位', () => {
    const s0 = runReducer(started, { type: 'stream-batch', tokens: 'a', deltas: [], seq: { runId: 'r1', seq: 5 } }).state
    const { state } = runReducer(s0, { type: 'stream-batch', tokens: 'b', deltas: [], seq: { runId: 'r1', seq: 3 } })
    expect(state.lastSeq).toEqual({ runId: 'r1', seq: 5 })
    expect(state.streamText).toBe('ab')
  })

  it('未识别事件不换 state 引用（no-op 渲染 bail）', () => {
    const r = runReducer(started, {
      type: 'sse',
      event: 'future.event',
      now: NOW,
      data: { run_id: 'r1', conversation_id: 'c1', seq: 2 },
    })
    expect(r.state).toBe(started)
  })

  it('重复 tool_call_id 幂等丢弃且不换引用', () => {
    const s0 = runReducer(started, taskCall).state
    const r = runReducer(s0, taskCall)
    expect(r.state).toBe(s0)
    expect(r.state.tools).toHaveLength(1)
  })
})
