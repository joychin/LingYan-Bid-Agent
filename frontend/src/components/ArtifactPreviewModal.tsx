import { useEffect } from 'react'
import { Copy, FileText, FolderOpen, X } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { isTauri, revealInFolder } from '@/api/client'
import { useArtifacts, useArtifactContent } from '@/hooks/useArtifacts'
import { ArtifactPreview } from '@/components/ArtifactPreview'
import { formatSize, cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

/** §9 产物预览覆盖层：居中模态，顶栏含「在文件夹中显示」；Esc / 遮罩关闭。 */
export function ArtifactPreviewModal({ artifactId, onClose }: { artifactId: string | null; onClose: () => void }) {
  const { data: artifacts = [] } = useArtifacts()
  const { data: content } = useArtifactContent(artifactId)
  const { toast } = useToast()
  const artifact: Artifact | undefined = artifacts.find((a) => a.id === artifactId)

  useEffect(() => {
    if (!artifactId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [artifactId, onClose])

  if (!artifactId || !artifact) return null

  const handleReveal = async () => {
    try {
      await revealInFolder(artifact.path)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  const handleCopyJson = async () => {
    const pretty = prettyJson(content?.content ?? '')
    try {
      await navigator.clipboard.writeText(pretty)
      toast('已复制', 'success')
    } catch {
      toast('复制失败', 'error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <div className="relative z-10 flex h-[85vh] w-[min(90vw,1000px)] flex-col overflow-hidden rounded-2xl border bg-card shadow-md">
        <div className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="truncate text-sm font-semibold">{artifact.name}</span>
          <span className="text-xs text-muted-foreground">
            {artifact.type.toUpperCase()} · {formatSize(artifact.size)}
          </span>
          <div className="ml-auto flex items-center gap-1">
            {artifact.type === 'json' && (
              <button
                type="button"
                onClick={handleCopyJson}
                className={cn(
                  'flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground',
                  'hover:bg-muted hover:text-foreground',
                )}
              >
                <Copy className="h-3.5 w-3.5" />
                复制
              </button>
            )}
            {isTauri() && (
              <button
                type="button"
                onClick={handleReveal}
                className={cn(
                  'flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground',
                  'hover:bg-muted hover:text-foreground',
                )}
              >
                <FolderOpen className="h-3.5 w-3.5" />
                在文件夹中显示
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="关闭"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <ArtifactPreview artifact={artifact} />
        </div>
      </div>
    </div>
  )
}

function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}
