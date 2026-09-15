import { describe, expect, it } from 'vitest'
import { buildWrapperDoc, RENDER_WIDTH } from './htmlRenderer'

/** webview 光栅化（2026-09-14 批二）：wrapper 构造纯函数——CSP/角标/视口宽三锁
 * 都在这里落，前端渲染本体（html2canvas 保真度）归实机验收不归单测。 */
describe('buildWrapperDoc', () => {
  const html = '<div style="padding:12px"><h2>待办中心</h2></div>'
  const doc = buildWrapperDoc(html)

  it('CSP：default-src none、样式内联、图片/字体仅 data:（杀外链与信标）', () => {
    expect(doc).toContain('http-equiv="Content-Security-Policy"')
    expect(doc).toContain("default-src 'none'")
    expect(doc).toContain("style-src 'unsafe-inline'")
    expect(doc).toContain('img-src data:')
    expect(doc).toContain('font-src data:')
  })

  it('角标：固定注入「界面原型 · 示意图」（机制注入，不依赖模型自觉）', () => {
    expect(doc).toContain('__proto_badge__')
    expect(doc).toContain('界面原型 · 示意图')
  })

  it('视口与承载：模型 HTML 原样进 #proto-root，body 宽=渲染视口', () => {
    expect(doc).toContain(`<div id="proto-root">${html}</div>`)
    expect(doc).toContain(`body { width: ${RENDER_WIDTH}px`)
  })

  it('自定义宽度生效（调用方可覆盖默认视口）', () => {
    expect(buildWrapperDoc(html, 900)).toContain('body { width: 900px')
  })
})
