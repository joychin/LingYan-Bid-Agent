import { describe, expect, it } from 'vitest'
import type { Message } from '@/api/client'
import { isLivePauseMessage, isRespondAnswer, lastInstructionText, splitMarker } from './hitlMessage'

function msg(role: Message['role'], content: string, run_id?: string): Message {
  return {
    id: Math.random().toString(36).slice(2),
    conversation_id: 'c1',
    role,
    content,
    created_at: '2026-08-29T00:00:00+00:00',
    run_id,
  }
}

describe('splitMarker', () => {
  it('识别暂停/中断标记并剥离正文', () => {
    expect(splitMarker('我先确认一下\n\n（等待你的输入…）')).toEqual({ body: '我先确认一下', marker: 'pause' })
    expect(splitMarker('半截回复\n\n（任务中断）')).toEqual({ body: '半截回复', marker: 'interrupted' })
    expect(splitMarker('普通消息')).toEqual({ body: '普通消息', marker: null })
  })

  it('裸标记消息（零旁白暂停，仅标记）识别为空正文', () => {
    expect(splitMarker('（等待你的输入…）')).toEqual({ body: '', marker: 'pause' })
    expect(splitMarker('（任务中断）')).toEqual({ body: '', marker: 'interrupted' })
  })
})

describe('isRespondAnswer', () => {
  it('紧随暂停消息的 user 消息是回答（含纯文字回答）', () => {
    const msgs = [
      msg('user', '开始检索'),
      msg('assistant', '请先选择起始册次。\n\n（等待你的输入…）'),
      msg('user', '技术册先行'), // 无「已选：」前缀的纯文字回答
      msg('assistant', '已确认：技术册先行。'),
    ]
    expect(isRespondAnswer(msgs, 2)).toBe(true)
    expect(isRespondAnswer(msgs, 0)).toBe(false)
    expect(isRespondAnswer(msgs, 3)).toBe(false)
  })

  it('「已选：」前缀恒为回答（历史信号，不依赖位置）', () => {
    const msgs = [
      msg('assistant', '问题\n\n（等待你的输入…）'),
      msg('user', '已选：A；B\n补充说明'),
      msg('user', '下一条指令'),
    ]
    expect(isRespondAnswer(msgs, 1)).toBe(true)
    expect(isRespondAnswer(msgs, 2)).toBe(false)
  })

  it('空数组与越界安全', () => {
    expect(isRespondAnswer([], 0)).toBe(false)
    expect(isRespondAnswer([msg('user', 'x')], 5)).toBe(false)
  })

  it('run_id 一致（同 run 的暂停+回答）识别为回答', () => {
    const msgs = [
      msg('assistant', '请先选择起始册次。\n\n（等待你的输入…）', 'run1'),
      msg('user', '技术册先行', 'run1'),
    ]
    expect(isRespondAnswer(msgs, 1)).toBe(true)
  })

  it('run_id 不一致（error 收尾后用户发新指令）不误判为回答', () => {
    const msgs = [
      msg('assistant', '半截回复\n\n（任务中断）', 'run1'),
      msg('user', '换成排查方案B', 'run2'),
    ]
    expect(isRespondAnswer(msgs, 1)).toBe(false)
    // 「重新执行」重发的正是这条新指令，而不是更早的旧指令
    expect(lastInstructionText(msgs)).toBe('换成排查方案B')
  })

  it('手打「已选：」但 run_id 不一致（新指令）不算回答', () => {
    const msgs = [
      msg('assistant', '最终回复', 'run1'),
      msg('user', '已选：方案A执行', 'run2'),
    ]
    expect(isRespondAnswer(msgs, 1)).toBe(false)
  })

  it('任一侧缺 run_id（迁移前历史数据）回退启发式', () => {
    const msgs = [
      msg('assistant', '请选择。\n\n（等待你的输入…）'),
      msg('user', '技术册先行'),
    ]
    expect(isRespondAnswer(msgs, 1)).toBe(true)
  })
})

describe('lastInstructionText', () => {
  it('跳过回答取最后一条真实指令', () => {
    const msgs = [
      msg('user', '开始检索'),
      msg('assistant', '问题\n\n（等待你的输入…）'),
      msg('user', '技术册先行'),
      msg('assistant', '完成'),
    ]
    expect(lastInstructionText(msgs)).toBe('开始检索')
  })

  it('纯文字回答也不会被误当指令', () => {
    const msgs = [
      msg('assistant', '问题\n\n（等待你的输入…）'),
      msg('user', '技术册先行'),
    ]
    expect(lastInstructionText(msgs)).toBe('')
  })
})

describe('isLivePauseMessage', () => {
  it('活卡存续 run 的暂停/中断半截消息隐藏', () => {
    expect(isLivePauseMessage(msg('assistant', '问题\n\n（等待你的输入…）', 'r1'), 'r1')).toBe(true)
    expect(isLivePauseMessage(msg('assistant', '半截\n\n（任务中断）', 'r1'), 'r1')).toBe(true)
  })

  it('非该 run / 非标记 / 非 assistant 的消息不隐藏', () => {
    expect(isLivePauseMessage(msg('assistant', '问题\n\n（等待你的输入…）', 'r1'), 'r2')).toBe(false)
    expect(isLivePauseMessage(msg('assistant', '普通最终回复', 'r1'), 'r1')).toBe(false)
    expect(isLivePauseMessage(msg('user', '（等待你的输入…）', 'r1'), 'r1')).toBe(false)
  })

  it('无活卡（终态）或 run_id 缺失（迁移前旧数据）不隐藏', () => {
    const pause = msg('assistant', '问题\n\n（等待你的输入…）', 'r1')
    expect(isLivePauseMessage(pause, null)).toBe(false)
    expect(isLivePauseMessage(pause, undefined)).toBe(false)
    expect(isLivePauseMessage(msg('assistant', '问题\n\n（等待你的输入…）'), 'r1')).toBe(false)
  })
})
