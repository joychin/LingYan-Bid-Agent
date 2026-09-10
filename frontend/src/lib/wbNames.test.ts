import { describe, expect, it } from 'vitest'
import { wbDisplayName } from './wbNames'

describe('wbDisplayName 工作台显示名', () => {
  it('固定过程文件走业务名（与产物面板行一致）', () => {
    expect(wbDisplayName('analysis/structure.md')).toBe('结构事实')
    expect(wbDisplayName('analysis/clarifications.md')).toBe('待澄清')
    expect(wbDisplayName('analysis/requirements-business.md')).toBe('商务技术要求')
    expect(wbDisplayName('outline/tender-response-docs.md')).toBe('目录底稿')
    expect(wbDisplayName('body/写作指引.md')).toBe('写作指引')
    expect(wbDisplayName('body/关键事实与承诺.md')).toBe('关键事实与承诺')
  })

  it('解析稿 = 源文件名 + 后缀（不酷似上传原件）', () => {
    expect(wbDisplayName('parse/AI--谈判文件.docx/AI--谈判文件.docx.md')).toBe(
      'AI--谈判文件.docx 解析稿',
    )
  })

  it('多册分册草稿 = 分册 · 册名（去扩展名）', () => {
    expect(wbDisplayName('outline/fragments/技术分册.md')).toBe('分册 · 技术分册')
  })

  it('其余走 basename（节 docx / 整本前缀不受影响）', () => {
    expect(wbDisplayName('body/封面.docx')).toBe('封面.docx')
    expect(wbDisplayName('body/技术分册/整本-技术分册.docx')).toBe('整本-技术分册.docx')
  })
})
