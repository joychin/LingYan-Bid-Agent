import { describe, expect, it } from 'vitest'
import { isFinishedStage, stageLabel } from './taskStage'

describe('stageLabel', () => {
  it('六阶段各有中文文案（与 sidecar task_stage.STAGES 同集合）', () => {
    expect(stageLabel('new')).toBe('刚开始')
    expect(stageLabel('parsed')).toBe('已解析')
    expect(stageLabel('analyzed')).toBe('要点已提取')
    expect(stageLabel('outlined')).toBe('目录已生成')
    expect(stageLabel('drafting')).toBe('正文写作中')
    expect(stageLabel('delivered')).toBe('已完结')
  })

  it('未知阶段原样回落（后端加新阶段时界面不空白）', () => {
    expect(stageLabel('reviewing')).toBe('reviewing')
  })

  it('空值返回空串（不渲染空胶囊）', () => {
    expect(stageLabel(null)).toBe('')
    expect(stageLabel(undefined)).toBe('')
    expect(stageLabel('')).toBe('')
  })
})

describe('isFinishedStage', () => {
  it('只有 delivered 算已完结', () => {
    expect(isFinishedStage('delivered')).toBe(true)
    expect(isFinishedStage('drafting')).toBe(false)
    expect(isFinishedStage(null)).toBe(false)
  })
})
