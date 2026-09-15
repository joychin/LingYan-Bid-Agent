/**
 * updateCheck 纯函数测试：版本比较 / 节流判定 / 检查时间人话化。
 * hook（useUpdateCheck）依赖 React Query 与 localStorage，不在单测范围（tauri dev 实测）。
 */

import { describe, expect, it } from 'vitest'
import { formatCheckedAt, isNewerVersion, shouldSkipNetwork } from './updateCheck'

describe('isNewerVersion', () => {
  it('逐段数值比较：patch/minor/major 各档', () => {
    expect(isNewerVersion('0.1.2', '0.1.0')).toBe(true)
    expect(isNewerVersion('0.2.0', '0.1.9')).toBe(true)
    expect(isNewerVersion('1.0.0', '0.9.9')).toBe(true)
    expect(isNewerVersion('0.1.0', '0.1.0')).toBe(false)
    expect(isNewerVersion('0.1.0', '0.1.2')).toBe(false)
    expect(isNewerVersion('0.0.9', '0.1.0')).toBe(false)
  })

  it('多位数段不踩字符串比较坑（0.10.0 > 0.9.x）', () => {
    expect(isNewerVersion('0.10.0', '0.9.0')).toBe(true)
    expect(isNewerVersion('0.9', '0.10.0')).toBe(false)
  })

  it('缺段补 0（0.2 视作 0.2.0）', () => {
    expect(isNewerVersion('0.2', '0.1.0')).toBe(true)
    expect(isNewerVersion('0.1', '0.1.0')).toBe(false)
  })

  it('容忍 v/V 前缀', () => {
    expect(isNewerVersion('v0.2.0', '0.1.0')).toBe(true)
    expect(isNewerVersion('V1.0.0', '0.9.9')).toBe(true)
  })

  it('不合法输入一律 false（宁漏报不误报）', () => {
    expect(isNewerVersion('abc', '0.1.0')).toBe(false)
    expect(isNewerVersion('0.1.x', '0.1.0')).toBe(false)
    expect(isNewerVersion('0.2.0', 'xyz')).toBe(false)
    expect(isNewerVersion('', '0.1.0')).toBe(false)
    expect(isNewerVersion('0.2.0', '')).toBe(false)
  })
})

describe('shouldSkipNetwork', () => {
  const now = 1_800_000_000_000
  it('从没查过 → 联网', () => {
    expect(shouldSkipNetwork(0, now)).toBe(false)
  })
  it('窗口内（<24h）成功过 → 跳过', () => {
    expect(shouldSkipNetwork(now - 60_000, now)).toBe(true)
    expect(shouldSkipNetwork(now - 23 * 3_600_000, now)).toBe(true)
  })
  it('超过 24h → 重新联网', () => {
    expect(shouldSkipNetwork(now - 25 * 3_600_000, now)).toBe(false)
  })
})

describe('formatCheckedAt', () => {
  const now = 1_800_000_000_000
  it('分级人话化', () => {
    expect(formatCheckedAt(now - 10_000, now)).toBe('刚刚')
    expect(formatCheckedAt(now - 5 * 60_000, now)).toBe('5 分钟前')
    expect(formatCheckedAt(now - 3 * 3_600_000, now)).toBe('3 小时前')
    expect(formatCheckedAt(now - 2 * 86_400_000, now)).toBe('2 天前')
  })
  it('时钟回拨不产生负数文案', () => {
    expect(formatCheckedAt(now + 60_000, now)).toBe('刚刚')
  })
})
