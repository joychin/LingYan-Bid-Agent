/**
 * runReducer 事件回放测试：fixture 驱动整条 SSE 事件管线（固定时钟，纯函数）。
 * 与 sidecar tests/test_contract.py 的同场景断言构成「封段规则双语言 parity」——
 * 两侧任何一边改了 tool.called 封段语义，对应测试需要同步修改。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentEventData } from '@/api/sse'
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
