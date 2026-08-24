import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Loader2 } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { useArtifactContent } from '@/hooks/useArtifacts'
import { markdownComponents } from '@/components/ChatMessage'

/** 产物预览：html → iframe(srcdoc, 仅 allow-scripts)；json → <pre>；md → markdown。 */
export function ArtifactPreview({ artifact }: { artifact: Artifact }) {
  const { data, isLoading, isError, error } = useArtifactContent(artifact.id)

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        加载产物内容…
      </div>
    )
  }
  if (isError || !data) {
    return <p className="text-sm text-red-600">加载失败：{error instanceof Error ? error.message : String(error)}</p>
  }

  if (artifact.type === 'html') {
    // tender-directory.html 自带弹窗 JS，必须 allow-scripts；不给 allow-same-origin（防触碰宿主上下文）
    return (
      <iframe
        title={artifact.name}
        sandbox="allow-scripts"
        srcDoc={data.content}
        className="h-full w-full flex-1 rounded-md border bg-white"
      />
    )
  }
  if (artifact.type === 'json') {
    let pretty = data.content
    try {
      pretty = JSON.stringify(JSON.parse(data.content), null, 2)
    } catch {
      /* 保留原文 */
    }
    return (
      <pre className="flex-1 overflow-auto rounded-md border bg-muted/30 p-3 text-xs leading-relaxed">
        {pretty}
      </pre>
    )
  }
  if (artifact.type === 'other') {
    // 未知类型按纯文本展示，避免二进制/乱码被当 markdown 渲染
    return (
      <pre className="flex-1 overflow-auto rounded-md border bg-muted/30 p-3 text-xs leading-relaxed">
        {data.content}
      </pre>
    )
  }
  // md
  return (
    <div className="prose-sm flex-1 overflow-auto rounded-md border bg-card p-4">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {data.content}
      </ReactMarkdown>
    </div>
  )
}
