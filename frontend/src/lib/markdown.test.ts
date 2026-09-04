import { describe, expect, it } from 'vitest'
import { stripCommentLines } from './markdown'

describe('stripCommentLines', () => {
  it('剔除产物头部元信息整行（含主文件名里夹的 --）', () => {
    const src =
      '<!-- tender-analysis | 节=clarifications | 主文件=AI--谈判文件.docx | 生成=2026-08-31T05:01:31+00:00 -->\n\n## 澄清与偏差\n\n正文'
    expect(stripCommentLines(src)).toBe('\n## 澄清与偏差\n\n正文')
  })

  it('剔除解析页码锚点行，正文与空行不动', () => {
    const src = '第一页内容\n<!-- p:2 -->\n第二页内容'
    expect(stripCommentLines(src)).toBe('第一页内容\n第二页内容')
  })

  it('行内注释不剔除', () => {
    const src = '正文 <!-- 行内备注 --> 继续'
    expect(stripCommentLines(src)).toBe(src)
  })

  it('无注释原样返回；纯注释文件返回空串（编辑器落 emptyLabel）', () => {
    expect(stripCommentLines('# 标题\n正文')).toBe('# 标题\n正文')
    expect(stripCommentLines('<!-- 仅注释 -->')).toBe('')
  })
})
