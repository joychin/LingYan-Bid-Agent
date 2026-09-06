import type { SidecarFailure } from '@/api/client'

/** FailureInfo.kind → 红态标题（detail 已是中文说明作副行；kind 缺失/未知给兜底标题）。 */
export function sidecarFailureTitle(failure: SidecarFailure | null | undefined): string {
  switch (failure?.kind) {
    case 'spawn_failed':
      return '服务进程拉起失败'
    case 'boot_timeout':
      return '服务启动超时'
    case 'crashed':
      return '服务意外崩溃'
    case 'exited':
      return '服务意外退出'
    default:
      return '服务启动失败'
  }
}
