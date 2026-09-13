/**
 * 整本标书 Processor（tender.volume/tender-volume-docx@1）：合册交付稿的只读预览。
 *
 * 文件型产物：content 是机器元信息（合并节数/图片/批注统计），docx 本体经
 * GET /artifacts/{aid}/file 取字节、docx-preview 本地渲染（与工作台 DocxView
 * 同一渲染体）。只读——整本是派生交付物（修订已按接受压平），改内容回节文件
 * 层改再重合册；下载/在文件夹中显示供交付取件。
 */

import { lazy, Suspense, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { fetchArtifactFile } from '@/api/client'
import { downloadBlob } from '@/lib/utils'
import type { ProcessorProps } from '@/artifacts/registry'

const DocxPreviewBody = lazy(() => import('../preview/DocxPreviewBody'))

interface VolumeMeta {
  filename?: string
  book?: string
  merged_sections?: number
  images?: number
  comments?: number
}

function parseVolume(raw: string): VolumeMeta | null {
  try {
    const obj = JSON.parse(raw) as Record<string, unknown>
    return {
      filename: typeof obj.filename === 'string' ? obj.filename : undefined,
      book: typeof obj.book === 'string' ? obj.book : undefined,
      merged_sections: typeof obj.merged_sections === 'number' ? obj.merged_sections : undefined,
      images: typeof obj.images === 'number' ? obj.images : undefined,
      comments: typeof obj.comments === 'number' ? obj.comments : undefined,
    }
  } catch {
    return null
  }
}

export function VolumeProcessor({ artifact, content }: ProcessorProps) {
  const [fallbackNote, setFallbackNote] = useState<string | null>(null)
  const meta = parseVolume(content)

  // key 带 content_seq：重合册发布后随列表刷新立即取新字节；前缀独立于
  // ['artifacts']——任何产物列表/内容 invalidate 不得连带重取整本几十 MB 的
  // blob（新 Blob 身份会触发整篇重渲染）。staleTime/gcTime 对齐 DocxView 的
  // 内存治理口径（关预览尽快释放）
  const file = useQuery({
    queryKey: ['artifact-file', artifact.artifact_id, artifact.content_seq],
    queryFn: () => fetchArtifactFile(artifact.artifact_id),
    staleTime: 30_000,
    gcTime: 2 * 60_000,
  })

  const filename = meta?.filename ?? `${artifact.display_name}.docx`
  const comments = meta?.comments ?? 0

  const handleDownload = () => {
    if (!file.data) return
    downloadBlob(filename, file.data)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-2 text-xs text-muted-foreground">
        {meta?.merged_sections != null && <span>合并 {meta.merged_sections} 节</span>}
        {meta?.images ? <span>图片 {meta.images} 张</span> : null}
        <span className={comments ? 'font-medium text-warning' : undefined}>
          待办批注 {comments} 条
        </span>
        <span className="ml-auto flex items-center gap-1">
          <button
            type="button"
            disabled={!file.data}
            onClick={handleDownload}
            title={`下载 ${filename}（打印/递交用 Word 副本）`}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            下载
          </button>
        </span>
      </div>
      {comments > 0 && (
        <p className="shrink-0 border-b bg-warning/10 px-4 py-1.5 text-xs text-warning">
          交付前请在 Word 中解决全部待办批注（正文旁高亮可见）；修订已按接受状态
          并入整本——本预览即交付效果。
        </p>
      )}
      {fallbackNote && (
        <p className="shrink-0 border-b bg-warning/10 px-4 py-1.5 text-xs text-warning">{fallbackNote}</p>
      )}
      {file.isLoading ? (
        <div className="p-4 text-xs text-muted-foreground">加载整本预览…（大文件可能需要数秒）</div>
      ) : file.isError ? (
        <div className="p-4 text-xs text-destructive">
          加载失败：{file.error instanceof Error ? file.error.message : String(file.error)}
        </div>
      ) : file.data ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <Suspense fallback={<div className="p-4 text-xs text-muted-foreground">加载预览组件…</div>}>
            <DocxPreviewBody
              data={file.data}
              onError={() => setFallbackNote('版式渲染失败（完整格式请下载后在 Word 中查看）')}
            />
          </Suspense>
        </div>
      ) : null}
    </div>
  )
}
