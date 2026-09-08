/**
 * docx 正文只读视图（tender-body 正文节 / 整本合册产物），双模式：
 * - 版式（默认）：docx-preview 浏览器本地渲染，所见即所得；渲染失败自动落回
 *   文本视图并提示一行（渲染体懒加载分包，见 preview/DocxPreviewBody）。
 * - 文本：段落编号 + 样式 + 图片/修订标记 + 表格概览的序列化——与模型侧
 *   docx_section_read 同一份视图（GET /workbench/docx-view）。
 *
 * 修订标记的审阅在 Word（「在文件夹中显示」双击打开）；编辑同样在 Word
 * （修订标记的审阅是 Word 的本职）。
 */

import { lazy, Suspense, useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen } from 'lucide-react'
import { fetchWorkbenchRaw, getWorkbenchDocxView, isTauri, revealInFolder } from '@/api/client'
import { cn } from '@/lib/utils'

const DocxPreviewBody = lazy(() => import('./preview/DocxPreviewBody'))

type Mode = 'layout' | 'text'

export function DocxView({ taskId, path }: { taskId: string | null; path: string | null }) {
  const [mode, setMode] = useState<Mode>('layout')
  const [fallbackNote, setFallbackNote] = useState<string | null>(null)

  // 文本视图 + abs_path（reveal 用）：常开（轻量序列化，兼作文件存在探测）
  const textView = useQuery({
    queryKey: ['workbench', taskId, 'docx-view', path],
    queryFn: async () => await getWorkbenchDocxView(taskId!, path!),
    enabled: !!taskId && !!path,
  })
  // 版式预览字节：只在版式模式拉（合册可能几十 MB）
  const raw = useQuery({
    queryKey: ['workbench', taskId, 'docx-raw', path],
    queryFn: async () => await fetchWorkbenchRaw(taskId!, path!),
    enabled: !!taskId && !!path && mode === 'layout',
  })

  const handlePreviewError = useCallback(() => {
    setFallbackNote('版式渲染失败，已切换到文本视图（完整格式请在 Word 中查看）')
    setMode('text')
  }, [])

  if (!path || !taskId) return null
  const display = path.split('/').pop() ?? path

  return (
    <div className="ap-ws">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b pl-4 pr-12 py-3">
        <span className="truncate text-sm font-semibold">{display}</span>
        <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-muted-foreground">Word 正文 · 只读</span>
        <div className="flex items-center rounded-md border border-line p-0.5 text-xs">
          {(['layout', 'text'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cn(
                'rounded px-2 py-0.5 transition-colors',
                mode === m
                  ? 'bg-muted font-medium text-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {m === 'layout' ? '版式' : '文本'}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-1">
          {isTauri() && textView.data && (
            <button
              type="button"
              onClick={() => void revealInFolder(textView.data.abs_path)}
              title="在文件夹中显示，双击用 Word 打开——格式与修订标记在 Word 中查看/审阅"
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              在文件夹中显示
            </button>
          )}
        </div>
      </div>
      {fallbackNote && mode === 'text' && (
        <p className="shrink-0 border-b bg-warning/10 px-4 py-1.5 text-xs text-warning">{fallbackNote}</p>
      )}
      {mode === 'layout' ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {raw.isLoading ? (
            <div className="p-4 text-xs text-muted-foreground">加载版式预览…</div>
          ) : raw.isError ? (
            <div className="p-4 text-xs text-destructive">
              加载失败：{raw.error instanceof Error ? raw.error.message : String(raw.error)}
            </div>
          ) : raw.data ? (
            <Suspense fallback={<div className="p-4 text-xs text-muted-foreground">加载预览组件…</div>}>
              <DocxPreviewBody data={raw.data} onError={handlePreviewError} />
            </Suspense>
          ) : null}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-auto p-4 font-mono text-xs leading-relaxed">
          {textView.isLoading ? (
            <span className="text-muted-foreground">加载正文视图…</span>
          ) : textView.isError ? (
            <span className="text-destructive">
              加载失败：{textView.error instanceof Error ? textView.error.message : String(textView.error)}
            </span>
          ) : (
            textView.data?.lines.map((ln, i) => (
              <p key={i} className="whitespace-pre-wrap break-words">
                {ln || '（空）'}
              </p>
            ))
          )}
        </div>
      )}
    </div>
  )
}
