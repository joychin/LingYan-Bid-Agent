/**
 * docx 正文只读视图（tender-body 正文节 / 整本合册产物）：
 * 段落编号 + 样式 + 图片/修订标记 + 表格概览的文本序列化——与模型侧
 * docx_section_read 是同一份视图（GET /workbench/docx-view）。
 *
 * 面板不渲染 docx 格式（修订标记没有任何轻量渲染方案能正确显示）：
 * 浏览内容结构用本视图，看真身/审修订标记经「在文件夹中显示」双击用 Word
 * 打开；编辑也在 Word（修订标记的审阅是 Word 的本职）。
 */

import { useQuery } from '@tanstack/react-query'
import { FolderOpen } from 'lucide-react'
import { getWorkbenchDocxView, isTauri, revealInFolder } from '@/api/client'

export function DocxView({ taskId, path }: { taskId: string | null; path: string | null }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['workbench', taskId, 'docx-view', path],
    queryFn: async () => await getWorkbenchDocxView(taskId!, path!),
    enabled: !!taskId && !!path,
  })

  if (!path || !taskId) return null
  const display = path.split('/').pop() ?? path

  return (
    <div className="ap-ws">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b pl-4 pr-12 py-3">
        <span className="truncate text-sm font-semibold">{display}</span>
        <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-muted-foreground">Word 正文 · 只读</span>
        <div className="ml-auto flex items-center gap-1">
          {isTauri() && data && (
            <button
              type="button"
              onClick={() => void revealInFolder(data.abs_path)}
              title="在文件夹中显示，双击用 Word 打开——格式与修订标记在 Word 中查看/审阅"
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              在文件夹中显示
            </button>
          )}
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-auto p-4 font-mono text-xs leading-relaxed">
        {isLoading ? (
          <span className="text-muted-foreground">加载正文视图…</span>
        ) : isError ? (
          <span className="text-destructive">加载失败：{error instanceof Error ? error.message : String(error)}</span>
        ) : (
          data?.lines.map((ln, i) => (
            <p key={i} className="whitespace-pre-wrap break-words">
              {ln || '（空）'}
            </p>
          ))
        )}
      </div>
    </div>
  )
}
