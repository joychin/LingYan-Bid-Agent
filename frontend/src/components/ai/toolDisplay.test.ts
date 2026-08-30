import { describe, expect, it } from 'vitest'
import { subagentStepTitle, toolDisplayName } from './toolDisplay'

describe('subagentStepTitle', () => {
  it('提示词纪律：首行 ≤24 字短名直接用作标题', () => {
    expect(
      subagentStepTitle({ description: '检索中石化 dify 相关招标\n在网上查找类似的招标公告，重点收集……' }),
    ).toBe('检索中石化 dify 相关招标')
  })

  it('无短名约定的首行按句读截第一句', () => {
    expect(subagentStepTitle({ description: '分析评分办法并提取废标条款。评分细节见第二行' })).toBe(
      '分析评分办法并提取废标条款。',
    )
  })

  it('第一句仍超 16 字硬截加省略号', () => {
    expect(subagentStepTitle({ description: '这是一段非常长的描述没有句读超过二十四个字符的测试文本继续写' })).toBe(
      '这是一段非常长的描述没有句读超过…',
    )
  })

  it('恰 16 字不截断（短名在第一行，详细任务从第二行起）', () => {
    const name = '一二三四五六七八九十一二三四五六'
    expect(name).toHaveLength(16)
    expect(subagentStepTitle({ description: `${name}\n第二行起是详细任务说明` })).toBe(name)
  })

  it('句读出现在行首 2 字内（「1.」编号）不按句读截', () => {
    expect(subagentStepTitle({ description: '1. 先检索中石化相关招标' })).toBe('1. 先检索中石化相关招标')
  })

  it('缺 description 回退 subagent_type，都缺返回空串', () => {
    expect(subagentStepTitle({ subagent_type: 'tender-outline-writer' })).toBe('tender-outline-writer')
    expect(subagentStepTitle({ description: '   ', subagent_type: 'tender-outline-writer' })).toBe(
      'tender-outline-writer',
    )
    expect(subagentStepTitle({ description: 42 })).toBe('')
    expect(subagentStepTitle()).toBe('')
  })

  it('空短名时调用方回退通用显示名', () => {
    expect(subagentStepTitle() || toolDisplayName('task')).toBe('派发子代理')
  })
})
