import { describe, expect, it } from 'vitest'
import { sidecarFailureTitle } from './sidecarFailure'

describe('sidecarFailureTitle', () => {
  it('按 kind 映射人话标题', () => {
    expect(sidecarFailureTitle({ kind: 'spawn_failed', detail: '' })).toBe('服务进程拉起失败')
    expect(sidecarFailureTitle({ kind: 'boot_timeout', detail: '' })).toBe('服务启动超时')
    expect(sidecarFailureTitle({ kind: 'crashed', detail: '' })).toBe('服务意外崩溃')
    expect(sidecarFailureTitle({ kind: 'exited', detail: '' })).toBe('服务意外退出')
  })

  it('未知/缺失 kind 回退通用标题', () => {
    expect(sidecarFailureTitle({ kind: 'future_kind', detail: '' } as never)).toBe('服务启动失败')
    expect(sidecarFailureTitle(null)).toBe('服务启动失败')
    expect(sidecarFailureTitle(undefined)).toBe('服务启动失败')
  })
})
