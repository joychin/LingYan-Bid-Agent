/**
 * 输入文件（sources/）只读预览宿主：按扩展名分流——pdf/docx 走版式预览
 * （浏览器本地渲染，渲染体懒加载分包，见 preview/），图片经 blob URL 直出
 * （KbImage 同款生命周期管理），其余类型给「不支持预览」提示 + reveal 兜底。
 * 上传原件此前只能右键「打开文件夹」，本组件让招标 pdf/docx 在面板内直接看。
 */

import { lazy, Suspense, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen } from 'lucide-react'
import { fetchSourceRaw, isTauri, revealInFolder } from '@/api/client'

const DocxPreviewBody = lazy(() => import('./preview/DocxPreviewBody'))
const PdfPreviewBody = lazy(() => import('./preview/PdfPreviewBody'))

const extOf = (name: string) => {
  const i = name.lastIndexOf('.')
  return i < 0 ? '' : name.slice(i).toLowerCase()
}

/** 面板可预览的来源类型（sourceRow 据此给可点行与光标）。 */
const PREVIEWABLE = new Set(['.pdf', '.docx', '.png', '.jpg', '.jpeg', '.gif', '.webp'])
export const sourcePreviewable = (name: string) => PREVIEWABLE.has(extOf(name))

const IMAGE = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp'])

export function SourceView({
  taskId,
  name,
  absPath,
}: {
  taskId: string | null
  name: string | null
  absPath?: string
}) {
  const ext = name ? extOf(name) : ''
  const isDoc = ext === '.docx'
  const isPdf = ext === '.pdf'
  const isImage = IMAGE.has(ext)

  const raw = useQuery({
    queryKey: ['source-raw', taskId, name],
    queryFn: async () => await fetchSourceRaw(taskId!, name!),
    enabled: !!taskId && !!name && (isDoc || isPdf),
  })

  // 图片：blob → objectURL（挂载期拥有，卸载/换图 revoke——KbImage 先例）
  const [imgUrl, setImgUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!isImage || !taskId || !name) return
    let url: string | null = null
    let alive = true
    void fetchSourceRaw(taskId, name)
      .then((blob) => {
        if (!alive) return
        url = URL.createObjectURL(blob)
        setImgUrl(url)
      })
      .catch(() => {
        /* 失败态由下方占位文案兜底 */
      })
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
      setImgUrl(null)
    }
  }, [isImage, taskId, name])

  if (!name || !taskId) return null

  const errText = raw.error instanceof Error ? raw.error.message : String(raw.error)

  return (
    <div className="ap-ws">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b pl-4 pr-12 py-3">
        <span className="truncate text-sm font-semibold">{name}</span>
        <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-muted-foreground">
          输入文件 · 只读
        </span>
        <div className="ml-auto flex items-center gap-1">
          {isTauri() && absPath && (
            <button
              type="button"
              onClick={() => void revealInFolder(absPath)}
              title="在文件夹中显示（用系统应用打开原件）"
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              在文件夹中显示
            </button>
          )}
        </div>
      </div>
      {isDoc || isPdf ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {raw.isLoading ? (
            <div className="p-4 text-xs text-muted-foreground">加载预览…</div>
          ) : raw.isError ? (
            <div className="p-4 text-xs text-destructive">加载失败：{errText}</div>
          ) : raw.data ? (
            <Suspense fallback={<div className="p-4 text-xs text-muted-foreground">加载预览组件…</div>}>
              {isPdf ? (
                <PdfPreviewBody data={raw.data} />
              ) : (
                <DocxPreviewBody data={raw.data} />
              )}
            </Suspense>
          ) : null}
        </div>
      ) : isImage ? (
        imgUrl ? (
          <div className="source-img-root">
            <img src={imgUrl} alt={name} />
          </div>
        ) : (
          <div className="p-4 text-xs text-muted-foreground">加载图片…</div>
        )
      ) : (
        <div className="p-4 text-xs text-muted-foreground">
          {ext === '.doc' ? (
            <>
              Word 97-2003 老格式（.doc）不支持预览——在 Word 中另存为 .docx
              后重新上传即可预览；或直接在文件夹中打开原件。
            </>
          ) : (
            <>该类型暂不支持面板预览，可在文件夹中用系统应用打开。</>
          )}
        </div>
      )}
    </div>
  )
}
