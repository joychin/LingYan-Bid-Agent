import { describe, expect, it } from 'vitest'

import { STREAM_TEXT_CAP, capStreamingText } from './streamTextCap'

describe('capStreamingText', () => {
  it('短文本原样返回、不折叠', () => {
    const r = capStreamingText('正在思考')
    expect(r.text).toBe('正在思考')
    expect(r.omitted).toBe(0)
  })

  it('恰好在上限时不折叠（<= cap）', () => {
    const text = 'a'.repeat(STREAM_TEXT_CAP)
    const r = capStreamingText(text)
    expect(r.omitted).toBe(0)
    expect(r.text).toBe(text)
  })

  it('超长时只保留尾部并给提示行', () => {
    const text = '前段'.repeat(3000) + '尾部标记XYZ' // 6000+ 字
    const r = capStreamingText(text)
    expect(r.omitted).toBe(text.length - STREAM_TEXT_CAP)
    expect(r.text).toContain(`⋯已折叠前 ${r.omitted} 字的思考，结束后可查看完整内容`)
    // 尾部切片原样衔接在提示行后
    expect(r.text.endsWith('\n\n' + text.slice(-STREAM_TEXT_CAP))).toBe(true)
  })

  it('自定义 cap 生效', () => {
    const r = capStreamingText('abcdef', 3)
    expect(r.omitted).toBe(3)
    expect(r.text.endsWith('def')).toBe(true)
  })

  it('自定义名词进提示行（活卡正文流复用同一封顶）', () => {
    const r = capStreamingText('abcdef', 3, '正文')
    expect(r.text).toContain('⋯已折叠前 3 字的正文，结束后可查看完整内容')
  })

  it('空字符串安全', () => {
    expect(capStreamingText('')).toEqual({ text: '', omitted: 0 })
  })
})
