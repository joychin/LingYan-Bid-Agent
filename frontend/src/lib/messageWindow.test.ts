import { describe, expect, it } from 'vitest'
import type { Message } from '@/api/client'
import { PAUSE_MARKER } from '@/lib/hitlMessage'
import { computeWindowStart } from './messageWindow'

let seq = 0
function msg(role: 'user' | 'assistant', content = 'x', runId: string | null = null): Message {
  return {
    id: `m${seq++}`,
    conversation_id: 'c1',
    role,
    content,
    created_at: '2026-09-06T00:00:00+00:00',
    run_id: runId,
  }
}

/** 一个 HITL 回合：user 指令 → 暂停半截（带标记）→ user 回答 → 最终回复 */
function turn(runId: string): Message[] {
  return [
    msg('user', '解析这份文件', runId),
    msg('assistant', '正在解析' + PAUSE_MARKER, runId),
    msg('user', '已选：确认', runId),
    msg('assistant', '解析完成', runId),
  ]
}

describe('computeWindowStart', () => {
  it('不足一窗时全量渲染', () => {
    expect(computeWindowStart([], 50)).toBe(0)
    expect(computeWindowStart(turn('r1'), 50)).toBe(0)
  })

  it('理想起点恰是普通 user 消息时直接采用', () => {
    const messages = [...turn('r1'), ...turn('r2'), ...turn('r3'), ...turn('r4'), ...turn('r5'), ...turn('r6')]
    // 长度 24，窗口 8 → 理想起点 16 恰是 r5 回合头（user 指令）
    expect(messages[16].role).toBe('user')
    expect(computeWindowStart(messages, 8)).toBe(16)
  })

  it('理想起点落在回合中间时回退到回合头（整回合进窗，分组不错位）', () => {
    const messages = [...turn('r1'), ...turn('r2'), ...turn('r3'), ...turn('r4'), ...turn('r5')]
    // 长度 20，窗口 9 → 理想起点 11 是 r3 的最终回复 assistant，回退到 8（r3 回合头）
    expect(messages[11].role).toBe('assistant')
    expect(computeWindowStart(messages, 9)).toBe(8)
  })

  it('理想起点是 HITL 回答消息时回退（回答隐藏逻辑依赖窗内有其前驱）', () => {
    const messages = [...turn('r1'), ...turn('r2'), ...turn('r3'), ...turn('r4'), ...turn('r5')]
    // 长度 20，窗口 14 → 理想起点 6 是 r2 的 user 回答（已选：确认），回退到 4（r2 回合头）
    expect(messages[6].content).toBe('已选：确认')
    expect(computeWindowStart(messages, 14)).toBe(4)
  })

  it('窗口极小时也停在最近回合头，不会切进回合内部', () => {
    const messages = [msg('assistant', 'a0'), ...turn('r1'), ...turn('r2'), ...turn('r3'), ...turn('r4'), ...turn('r5')]
    // 长度 21，窗口 2 → 理想起点 19 是 r5 的 user 回答，回退到 17（r5 回合头）
    expect(computeWindowStart(messages, 2)).toBe(17)
  })

  it('找不到任何回合头（纯 assistant 序列）时回退到全量', () => {
    const messages = Array.from({ length: 10 }, () => msg('assistant'))
    expect(computeWindowStart(messages, 4)).toBe(0)
  })
})
