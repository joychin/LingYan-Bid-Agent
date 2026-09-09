/**
 * 原件预览宿主（知识库条目 / 素材库文件共用）：原始文件的版式渲染，
 * pdf/docx 走 preview/ 懒加载分包（文件不出本机）。字节经 source.fetchBlob
 * （useQuery 缓存，queryKey 由宿主给——知识库 retrigger 时按键失效）。
 * 知识库的「回原文核对」与素材库的「看原文版式/图表」同一形态。
 */
import { lazy, Suspense, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileWarning } from 'lucide-react'

const PdfPreviewBody = lazy(() => import('@/components/preview/PdfPreviewBody'))
const DocxPreviewBody = lazy(() => import('@/components/preview/DocxPreviewBody'))

const DOC_HINT = '.doc 是老版 Word 格式，暂不能在线预览——请用 Word 另存为 .docx 后重新上传'

/** 原件源：id + 扩展名 + 取字节函数 + 查询缓存键（不同库的失效节奏不同，键归宿主定）。 */
export interface OriginalSource {
  id: string
  ext: string
  fetchBlob: (id: string) => Promise<Blob>
  queryKey: readonly unknown[]
  /** 版式渲染失败的兜底提示（原件在哪因库而异）。 */
  failHint?: string
}

/** 该扩展名是否支持原件预览（宿主据此决定是否显示切换）。 */
export function originalPreviewable(ext: string): boolean {
  const e = ext.toLowerCase()
  return e === '.pdf' || e === '.docx' || e === '.doc'
}

export function OriginalView({ source }: { source: OriginalSource }) {
  const ext = source.ext.toLowerCase()
  const [renderFailed, setRenderFailed] = useState(false)
  const raw = useQuery({
    queryKey: source.queryKey,
    queryFn: () => source.fetchBlob(source.id),
    enabled: ext === '.pdf' || ext === '.docx',
    staleTime: Infinity, // 原件只在整文件替换时变化（知识库 retrigger 按键失效；素材库原件不可变）
    gcTime: 10 * 60_000,
  })

  if (ext === '.doc') {
    return (
      <div className="original-hint">
        <FileWarning className="h-4 w-4" />
        {DOC_HINT}
      </div>
    )
  }
  if (renderFailed) {
    return (
      <div className="original-hint">
        <FileWarning className="h-4 w-4" />
        {source.failHint ?? '版式渲染失败——请用 Word/PDF 阅读器打开原件'}
      </div>
    )
  }
  if (raw.isLoading) {
    return <div className="original-loading">加载原件…</div>
  }
  if (raw.isError || !raw.data) {
    return (
      <div className="original-hint">
        <FileWarning className="h-4 w-4" />
        原件加载失败：{raw.error instanceof Error ? raw.error.message : '未知错误'}
      </div>
    )
  }
  const blob = raw.data
  return (
    <Suspense fallback={<div className="original-loading">加载预览组件…</div>}>
      {ext === '.pdf' ? (
        <PdfPreviewBody data={blob} onError={() => setRenderFailed(true)} />
      ) : (
        <DocxPreviewBody data={blob} onError={() => setRenderFailed(true)} />
      )}
    </Suspense>
  )
}
