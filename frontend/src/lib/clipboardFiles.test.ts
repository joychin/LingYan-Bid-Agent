import { describe, expect, it } from 'vitest'
import { renameClipboardNames } from './clipboardFiles'

const NOW = new Date(2026, 8, 13, 15, 30, 45) // 2026-09-13 15.30.45（本地时区）

describe('renameClipboardNames', () => {
  it('通用剪贴板名改为「截图 时间戳.扩展名」', () => {
    expect(renameClipboardNames(['image.png'], NOW)).toEqual(['截图 2026-09-13 15.30.45.png'])
  })

  it('大小写不敏感匹配通用名，扩展名保留', () => {
    expect(renameClipboardNames(['Image.PNG', 'image.jpeg'], NOW)).toEqual([
      '截图 2026-09-13 15.30.45.PNG',
      '截图 2026-09-13 15.30.45.jpeg',
    ])
  })

  it('同批同名加序号（两次粘贴截图落在同一秒的兜底）', () => {
    expect(renameClipboardNames(['image.png', 'image.png'], NOW)).toEqual([
      '截图 2026-09-13 15.30.45.png',
      '截图 2026-09-13 15.30.45 (2).png',
    ])
  })

  it('真名文件保持原名（Finder 复制粘贴，重传覆盖语义不受影响）', () => {
    expect(renameClipboardNames(['招标文件.docx', 'image.png'], NOW)).toEqual([
      '招标文件.docx',
      '截图 2026-09-13 15.30.45.png',
    ])
  })

  it('真名文件批内重名同样加序号', () => {
    expect(renameClipboardNames(['a.pdf', 'a.pdf'], NOW)).toEqual(['a.pdf', 'a (2).pdf'])
  })

  it('空名兜底为截图命名（个别环境无名粘贴）', () => {
    expect(renameClipboardNames([''], NOW)).toEqual(['截图 2026-09-13 15.30.45.png'])
  })
})
