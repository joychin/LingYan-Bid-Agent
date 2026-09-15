import { describe, expect, it } from 'vitest'
import { computeTipPosition } from './HoverTip'

// 常量对齐组件：OFFSET_X=14 / OFFSET_Y=20 / VIEWPORT_MARGIN=8
describe('computeTipPosition（气泡视口收拢）', () => {
  it('常规位置：光标右下方', () => {
    expect(computeTipPosition(100, 100, 200, 40, 1280, 800)).toEqual({ left: 114, top: 120 })
  })

  it('右侧放不下：翻到光标左侧', () => {
    const vw = 300
    const { left } = computeTipPosition(280, 100, 200, 40, vw, 800)
    // 280+14+200 > 300-8 → 280-200-14=66
    expect(left).toBe(66)
  })

  it('底部放不下：翻到光标上方', () => {
    const { top } = computeTipPosition(100, 790, 200, 40, 1280, 800)
    // 790+20+40 > 800-8 → 790-40-20=730
    expect(top).toBe(730)
  })

  it('两侧都窄：左坐标钳在边距，不出负值', () => {
    const { left } = computeTipPosition(5, 100, 200, 40, 120, 800)
    // 5-200-14<8 → 钳 8
    expect(left).toBe(8)
  })
})
