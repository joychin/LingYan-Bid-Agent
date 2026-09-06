import { describe, expect, it } from 'vitest'
import { normalizeToolSteps } from './toolSteps'

describe('normalizeToolSteps（历史 trace 松散 dict 防御）', () => {
  it('缺 children/text/status 等键的旧快照补默认值不抛错', () => {
    const out = normalizeToolSteps([{ tool: 'task', summary: 'x' }, { id: 'a', tool: 'grep' }])
    expect(out[0]!.children).toEqual([])
    expect(out[0]!.status).toBe('done')
    expect(out[0]!.reasoning).toBe('')
    expect(out[0]!.id).toBe('step-0')
    expect(out[1]!.id).toBe('a')
  })

  it('递归归一子代理 children', () => {
    const out = normalizeToolSteps([{ id: 't', tool: 'task', children: [{ tool: 'grep' }] }])
    expect(out[0]!.children[0]!.children).toEqual([])
    expect(out[0]!.children[0]!.id).toBe('step-0')
  })

  it('非数组输入整体回退空数组', () => {
    expect(normalizeToolSteps(null)).toEqual([])
    expect(normalizeToolSteps(undefined)).toEqual([])
    expect(normalizeToolSteps({})).toEqual([])
  })

  it('合法字段原样保留（含 paused/error/text）', () => {
    const out = normalizeToolSteps([
      {
        id: 'x',
        tool: 'write_file',
        status: 'paused',
        error: 'boom',
        text: '旁白',
        reasoning: '思考',
        startedAt: 1,
        endedAt: 2,
        toolCallId: 'tc',
        summary: 's',
        args: { path: 'a.md' },
      },
    ])
    expect(out[0]).toEqual({
      id: 'x',
      tool: 'write_file',
      status: 'paused',
      error: 'boom',
      text: '旁白',
      reasoning: '思考',
      startedAt: 1,
      endedAt: 2,
      toolCallId: 'tc',
      summary: 's',
      args: { path: 'a.md' },
      children: [],
    })
  })

  it('未知 status 值兜底为 done（历史树里 running 不会持久化）', () => {
    const out = normalizeToolSteps([{ id: 'x', tool: 'grep', status: 'weird' }])
    expect(out[0]!.status).toBe('done')
  })
})
