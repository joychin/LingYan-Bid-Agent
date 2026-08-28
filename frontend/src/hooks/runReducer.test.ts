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
  it('旁白封段：tool.called 把之前正文封为 step.text 并清空 streamText', () => {
    const { state, effects } = replay(normal.events)
    expect(state.tools).toHaveLength(1)
    expect(state.tools[0].text).toBe('我先查一下资料。') // 旁白挂到工具步骤
    expect(state.tools[0].status).toBe('done')
    expect(state.streamText).toBe('完成了：X。') // 最后未封口段 = 最终回复
    expect(state.reasoningText).toBe('想想')
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
