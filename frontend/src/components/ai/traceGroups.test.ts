import { describe, expect, it } from 'vitest'
import type { ToolStep } from '@/api/sse'
import { segmentToolSteps, type TraceSegment } from './traceGroups'

let seq = 0
function step(tool: string, over: Partial<ToolStep> = {}): ToolStep {
  seq += 1
  return {
    id: `s${seq}`,
    tool,
    args: {},
    status: 'done',
    summary: '',
    reasoning: '',
    children: [],
    startedAt: 0,
    ...over,
  }
}
function grep(pattern: string, over: Partial<ToolStep> = {}): ToolStep {
  return step('grep', { args: { pattern }, ...over })
}
/** 段落形状速记：组带数量、单步骤只带工具名，便于整列断言 */
function shape(segments: TraceSegment[]): string[] {
  return segments.map((s) =>
    s.kind === 'ask' || s.kind === 'grep' ? `${s.kind}(${s.steps.length})` : `${s.kind}:${s.step.tool}`,
  )
}

describe('segmentToolSteps', () => {
  it('相邻 grep ≥2 收进一组', () => {
    expect(shape(segmentToolSteps([grep('无效'), grep('否决'), grep('拒收')]))).toEqual(['grep(3)'])
  })

  it('单个 grep 不成组（自扩词等孤立反查维持普通步骤行）', () => {
    expect(shape(segmentToolSteps([grep('作无效标处理')]))).toEqual(['tool:grep'])
  })

  it('旁白断组：同轮只有首个调用携带封段旁白，10+10 两批成两组', () => {
    const batch1 = Array.from({ length: 10 }, (_, i) =>
      grep(`词${i}`, i === 0 ? { text: '开始废标条款全扫反查' } : {}),
    )
    const batch2 = Array.from({ length: 10 }, (_, i) =>
      grep(`词b${i}`, i === 0 ? { text: '继续反查剩余词表' } : {}),
    )
    expect(shape(segmentToolSteps([...batch1, ...batch2]))).toEqual(['grep(10)', 'grep(10)'])
  })

  it('仅思考（reasoning 非空、旁白为空）同样断组', () => {
    const steps = [
      grep('无效'),
      grep('否决'),
      grep('拒收'),
      grep('不予受理', { reasoning: '换批继续查' }),
      grep('不合格'),
    ]
    expect(shape(segmentToolSteps(steps))).toEqual(['grep(3)', 'grep(2)'])
  })

  it('旧 trace 无 text 字段：20 词并成一组（无可断的旁白）', () => {
    const steps = Array.from({ length: 20 }, (_, i) => {
      const s = grep(`词${i}`)
      delete (s as Partial<ToolStep>).text
      return s
    })
    expect(shape(segmentToolSteps(steps))).toEqual(['grep(20)'])
  })

  it('交错拆散：grep-read_file-grep 不合并（不同阶段）', () => {
    expect(
      shape(segmentToolSteps([grep('无效'), step('read_file'), grep('无效回应措辞')])),
    ).toEqual(['tool:grep', 'tool:read_file', 'tool:grep'])
  })

  it('ask_human 分组行为不变：连续段收拢、与 grep 相邻时按序互不吞并', () => {
    expect(
      shape(
        segmentToolSteps([
          step('ask_human'),
          step('ask_human'),
          grep('无效'),
          grep('否决'),
          step('ask_human'),
        ]),
      ),
    ).toEqual(['ask(2)', 'grep(2)', 'ask(1)'])
  })

  it('task 透传且隔断两侧 grep 批', () => {
    expect(
      shape(segmentToolSteps([grep('无效'), grep('否决'), step('task'), grep('废标'), grep('作废')])),
    ).toEqual(['grep(2)', 'task:task', 'grep(2)'])
  })

  it('空列表与纯普通工具', () => {
    expect(shape(segmentToolSteps([]))).toEqual([])
    expect(shape(segmentToolSteps([step('ls'), step('write_file')]))).toEqual([
      'tool:ls',
      'tool:write_file',
    ])
  })
})
