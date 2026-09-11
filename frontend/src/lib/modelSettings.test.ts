import { describe, expect, it } from 'vitest'
import { findKeySource, mergeModelOptions } from './modelSettings'

const m = (id: string, baseUrl: string, keySaved: boolean) => ({ id, baseUrl, keySaved })

describe('findKeySource', () => {
  it('命中同厂商已配 Key 的兄弟（尾部斜杠归一）', () => {
    const models = [m('a', 'https://api.deepseek.com/v1', true)]
    expect(findKeySource(models, 'https://api.deepseek.com/v1/')?.id).toBe('a')
  })

  it('排除自身（编辑时不提示复用自己）', () => {
    const models = [m('a', 'https://api.deepseek.com/v1', true)]
    expect(findKeySource(models, 'https://api.deepseek.com/v1', 'a')).toBeNull()
  })

  it('未配 Key 的兄弟不算命中', () => {
    const models = [m('a', 'https://api.deepseek.com/v1', false)]
    expect(findKeySource(models, 'https://api.deepseek.com/v1')).toBeNull()
  })

  it('不同厂商不命中；空地址不命中', () => {
    const models = [m('a', 'https://api.deepseek.com/v1', true)]
    expect(findKeySource(models, 'https://api.moonshot.cn/v1')).toBeNull()
    expect(findKeySource(models, '   ')).toBeNull()
  })
})

describe('mergeModelOptions', () => {
  it('拉取清单 + 常用分组：拉到的进「服务商提供」，未拉到的预设进「常用」', () => {
    const groups = mergeModelOptions(
      ['deepseek-v4-flash', 'brand-new-model'],
      [
        { name: 'deepseek-v4-flash', imageSupport: false },
        { name: 'deepseek-v4-pro', imageSupport: false },
      ],
    )
    expect(groups.map((g) => g.label)).toEqual(['服务商提供', '常用'])
    // 拉取组的预设命中项补回 imageSupport 元数据
    expect(groups[0].models).toEqual([
      { name: 'deepseek-v4-flash', imageSupport: false },
      { name: 'brand-new-model', imageSupport: undefined },
    ])
    // 已在拉取组里的预设不重复出现在常用组
    expect(groups[1].models.map((x) => x.name)).toEqual(['deepseek-v4-pro'])
  })

  it('拉取为空 → 只出「常用」组（失败静默回落）', () => {
    const groups = mergeModelOptions([], [{ name: 'x-1' }])
    expect(groups).toEqual([{ label: '常用', models: [{ name: 'x-1' }] }])
  })

  it('拉取清单去重、去空白', () => {
    const groups = mergeModelOptions(['a', 'a', ' a ', ''], [])
    expect(groups[0].models.map((x) => x.name)).toEqual(['a'])
  })

  it('两组都空 → 空数组', () => {
    expect(mergeModelOptions([], [])).toEqual([])
  })
})
