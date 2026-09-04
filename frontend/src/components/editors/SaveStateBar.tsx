/**
 * 保存状态条（2026-09-04 编辑基建统一）：三个编辑表面头部恒显的保存状态指示。
 * 老工程 SectionEditorStage 四态先例的薄版——用户随时知道「存上没有」。
 * conflict 不在此裁决（各表面的冲突横幅承接），这里只显示「有新版本」提示。
 */

import type { AutoSaveState } from '@/hooks/useAutoSave'
import { Loader } from '@/components/ai/Loader'
import { cn } from '@/lib/utils'

function timeLabel(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60_000) return '刚刚'
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

export function SaveStateBar({
  state,
  lastSavedAt,
  onRetry,
  className,
}: {
  state: AutoSaveState
  lastSavedAt: number | null
  onRetry: () => void
  className?: string
}) {
  if (state === 'idle') return null
  return (
    <span className={cn('flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground', className)}>
      {state === 'saving' && (
        <>
          <Loader variant="circular" size="xs" tone="muted" />
          <span>保存中…</span>
        </>
      )}
      {state === 'dirty' && (
        <>
          <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden />
          <span>未保存</span>
        </>
      )}
      {state === 'saved' && (
        <span>{lastSavedAt ? `已保存 · ${timeLabel(lastSavedAt)}` : '已保存'}</span>
      )}
      {state === 'error' && (
        <button type="button" onClick={onRetry} className="text-destructive hover:underline">
          保存失败 · 点击重试
        </button>
      )}
      {state === 'conflict' && <span className="text-warning">有新版本 · 请在上方提示中选择</span>}
    </span>
  )
}
