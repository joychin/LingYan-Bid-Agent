/**
 * 来源追溯弹窗（2026-09-04 目录查看增强）：点击目录节点上的来源徽章
 * （MAND/TPL/REQ/SCORE）展示登记条目——类型 / 原文 / 出处。数据全部来自
 * 产物契约内的 registry（零后端改动）。「查看原文上下文」动作由宿主注入
 * （批次 3 CodeMirror 行号定位落地后点亮），未注入时不渲染。
 */

import { useEffect } from 'react'
import { FileSearch } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'

export interface SourceEntry {
  type?: string
  text?: string
  出处?: string
}

export function SourceTraceDialog({
  traceId,
  entry,
  onClose,
  onOpenSource,
}: {
  traceId: string | null
  entry: SourceEntry | undefined
  onClose: () => void
  /** 解析出处并跳转原文（含行号定位）；缺省不渲染入口 */
  onOpenSource?: (id: string, entry: SourceEntry) => void
}) {
  useEffect(() => {
    if (!traceId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [traceId, onClose])

  if (!traceId) return null
  return (
    <Dialog open onClose={onClose} title={`来源追溯 · ${traceId}`}>
      {entry ? (
        <div className="flex flex-col gap-4 text-sm">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {entry.type && (
              <span className="rounded-full bg-muted px-2 py-0.5 font-medium text-ink-2">{entry.type}</span>
            )}
            {entry.出处 && <span className="min-w-0 truncate">{entry.出处}</span>}
          </div>
          <blockquote className="rounded-lg border border-line bg-muted/40 px-4 py-3 leading-relaxed">
            {entry.text || '（登记表未存原文，出处见上方）'}
          </blockquote>
          {onOpenSource && (
            <button
              type="button"
              onClick={() => onOpenSource(traceId, entry)}
              className="flex w-fit items-center gap-1.5 rounded-md border border-line bg-card px-3 py-1.5 text-xs font-medium hover:border-primary"
            >
              <FileSearch className="h-3.5 w-3.5" />
              查看原文上下文
            </button>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          登记表中没有 {traceId} 的条目（引用悬空）——可能是目录引用了不存在的来源编号。
        </p>
      )}
    </Dialog>
  )
}
