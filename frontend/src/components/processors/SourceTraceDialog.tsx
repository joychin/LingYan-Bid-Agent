/**
 * 来源追溯弹窗（2026-09-04 目录查看增强）：点击目录节点上的来源徽章
 * （MAND/TPL/REQ/SCORE）展示登记条目——类型 / 原文 / 出处。数据全部来自
 * 产物契约内的 registry（零后端改动）。
 *
 * 2026-09-09 上下文内嵌：条目卡片直接展示出处行号附近的原文切片
 * （ParseContextBlock，替代「跳转解析文件定位」——跳转离开当前界面且定位
 * 感知弱，用户拍板就地展示）。
 */

import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import { Dialog } from '@/components/ui/dialog'
import { getWorkbenchContent } from '@/api/client'
import { useWorkbench } from '@/hooks/useWorkbench'
import { cn } from '@/lib/utils'

export interface SourceEntry {
  type?: string
  text?: string
  出处?: string
}

/** 出处文本 → 首个行号（L440 / L1420-L1439 取起始；无行号 null）。 */
export function sourceLine(source?: string): number | null {
  const m = source?.match(/L(\d+)/)
  return m ? Number(m[1]) : null
}

/** 出处原文上下文（就地展示，2026-09-09）：按出处行号取解析主文件 md 的
 *  line-8 ~ line+12 切片，目标行高亮。解析主文件=workbench 列表 parse/ 下
 *  首个条目（单主文件场景，与旧跳转口径一致）；content 查询与面板共享缓存。
 *  无任务/无解析文件/出处无行号 → 各自降级不渲染（提示行号缺失）。 */
export function ParseContextBlock({
  taskId,
  source,
}: {
  taskId: string | null | undefined
  source?: string
}) {
  const line = sourceLine(source)
  const { data: wbFiles } = useWorkbench(taskId ?? null)
  const parsePath = useMemo(
    () => (wbFiles ?? []).find((f) => f.path.startsWith('parse/') && f.path.endsWith('.md'))?.path ?? null,
    [wbFiles],
  )
  const { data: raw, isLoading } = useQuery({
    queryKey: ['workbench', taskId ?? null, 'content', parsePath],
    queryFn: async () => await getWorkbenchContent(taskId!, parsePath!),
    enabled: !!taskId && !!parsePath && line !== null,
    staleTime: 30_000,
  })

  if (line === null) {
    return <p className="text-xs text-muted-foreground">出处未带行号，无法定位原文上下文。</p>
  }
  if (!taskId || !parsePath) return null
  if (isLoading || !raw) return <p className="text-xs text-muted-foreground">正在加载原文上下文…</p>

  const lines = raw.content.split('\n')
  const from = Math.max(1, line - 8)
  const to = Math.min(lines.length, line + 12)
  const fileName = parsePath.split('/').pop() ?? ''
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="flex items-center gap-1.5 border-b border-line bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
        <FileText className="h-3 w-3 shrink-0" />
        <span className="min-w-0 truncate">
          原文上下文 L{from}-L{to} · {fileName}
        </span>
      </div>
      <div className="max-h-64 overflow-auto px-1 py-1">
        {Array.from({ length: to - from + 1 }, (_v, k) => {
          const n = from + k
          const hit = n === line
          return (
            <div
              key={n}
              className={cn(
                'flex gap-2 rounded px-2 py-px text-xs leading-relaxed',
                hit ? 'bg-accent-soft font-medium text-foreground' : 'text-ink-2',
              )}
            >
              <span className={cn('w-9 shrink-0 select-none text-right tabular-nums', hit ? 'text-primary' : 'text-ink-3')}>
                {n}
              </span>
              <span className="min-w-0 whitespace-pre-wrap break-words">{lines[n - 1] || ' '}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** 登记条目卡片（type 徽章 + 出处 + 原文引用块 + 原文上下文切片）——
 *  来源追溯弹窗与写作指引行展开面板共用。上下文块需 taskId（拉解析主文件）。 */
export function SourceEntryCard({
  entry,
  taskId,
}: {
  entry: SourceEntry
  taskId?: string | null
}) {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {entry.type && (
          <span className="rounded-full bg-muted px-2 py-0.5 font-medium text-ink-2">{entry.type}</span>
        )}
        {entry.出处 && <span className="min-w-0 truncate">{entry.出处}</span>}
      </div>
      <blockquote className="rounded-lg border border-line bg-muted/40 px-4 py-3 leading-relaxed">
        {entry.text || '（登记表未存原文，出处见上方）'}
      </blockquote>
      {taskId !== undefined && <ParseContextBlock taskId={taskId} source={entry.出处} />}
    </div>
  )
}

export function SourceTraceDialog({
  traceId,
  entry,
  onClose,
  taskId,
}: {
  traceId: string | null
  entry: SourceEntry | undefined
  onClose: () => void
  /** 原文上下文切片的数据来源（当前任务）；缺省不渲染上下文块 */
  taskId?: string | null
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
        <SourceEntryCard entry={entry} taskId={taskId} />
      ) : (
        <p className="text-sm text-muted-foreground">
          登记表中没有 {traceId} 的条目（引用悬空）——可能是目录引用了不存在的来源编号。
        </p>
      )}
    </Dialog>
  )
}
