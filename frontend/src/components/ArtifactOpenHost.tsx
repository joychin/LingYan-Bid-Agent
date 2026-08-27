/**
 * Artifact Open Host（artifact-system-design.md §6）：点击产物后的统一容器。
 *
 * 职责仅限通用层：模态壳、内容加载、Resolver 唤起 Processor、loading/error/不支持态、
 * 标题栏与通用动作（Tauri 定位文件）。不感知任何契约的领域结构。
 */

import { useEffect } from 'react'
import { FileText, FolderOpen, Puzzle, X } from 'lucide-react'
import { artifactKey, isTauri, revealInFolder } from '@/api/client'
import { useArtifacts, useArtifactContent } from '@/hooks/useArtifacts'
import { contractLabel, resolveProcessor } from '@/artifacts/registry'
import { formatRelativeTime, cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

export function ArtifactOpenHost({ artifactId, onClose }: { artifactId: string | null; onClose: () => void }) {
  const { data: artifacts = [] } = useArtifacts()
  const { data, isLoading, isError, error } = useArtifactContent(artifactId)
  const { toast } = useToast()
  const artifact = artifacts.find((a) => a.artifact_id === artifactId)

  useEffect(() => {
    if (!artifactId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [artifactId, onClose])

  if (!artifactId || !artifact) return null

  const processor = resolveProcessor(artifact)

  const handleReveal = async () => {
    try {
      await revealInFolder(artifact.path)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <div className="relative z-10 flex h-[85vh] w-[min(90vw,1000px)] flex-col overflow-hidden rounded-2xl border bg-card shadow-md">
        <div className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <span className="truncate text-sm font-semibold">{artifact.display_name}</span>
          <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-muted-foreground">
            {contractLabel(artifact.kind)}
          </span>
          <span
            className="hidden text-xs text-muted-foreground md:inline"
            title={artifactKey(artifact)}
          >
            {formatRelativeTime(artifact.updated_at)}
          </span>
          <div className="ml-auto flex items-center gap-1">
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
          {isLoading ? (
            <p className="py-4 text-center text-sm text-muted-foreground">加载产物内容…</p>
          ) : isError || !data ? (
            <p className="py-4 text-center text-sm text-red-600">
              加载失败：{error instanceof Error ? error.message : String(error)}
            </p>
          ) : processor ? (
            <processor.Component artifact={artifact} content={data.content} />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <Puzzle className="h-8 w-8 text-muted-foreground" strokeWidth={1.5} />
              <p className="text-sm font-medium">当前客户端不支持该 Artifact 类型</p>
              <p className="text-xs text-muted-foreground">{artifactKey(artifact)}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
