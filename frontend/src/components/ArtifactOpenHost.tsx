/**
 * Artifact Open Host（artifact-system-design.md §6）· v3 工作区形态。
 *
 * v3 起**不再是居中模态**：由 ArtifactPanel 的工作区态（.ap-ws）渲染，与导航列并排
 * （方案 v2：常规查看/编辑不进模态，模态只留给不可逆确认）。职责仍限通用层——
 * 内容加载、Resolver 唤起 Processor、loading/error/不支持态、作用域徽标与通用动作。
 * 不感知任何契约的领域结构。
 */

import { FileText, FolderOpen, Puzzle } from 'lucide-react'
import { artifactKey, isTauri, revealInFolder } from '@/api/client'
import { useArtifacts, useArtifactContent } from '@/hooks/useArtifacts'
import { contractLabel, resolveProcessor } from '@/artifacts/registry'
import { formatRelativeTime, cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

export function ArtifactOpenHost({ artifactId }: { artifactId: string | null }) {
  const { data: artifacts = [] } = useArtifacts()
  const { data, isLoading, isError, error } = useArtifactContent(artifactId)
  const { toast } = useToast()
  const artifact = artifacts.find((a) => a.artifact_id === artifactId)

  if (!artifactId || !artifact) return null

  const processor = resolveProcessor(artifact)
  const formal = artifact.scope === 'task'

  const handleReveal = async () => {
    try {
      await revealInFolder(artifact.path)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <div className="ap-ws">
      <div className="ap-ws-head">
        <FileText className="ap-ws-docico" />
        <span className="ap-ws-title">{artifact.display_name}</span>
        <span className={cn('ap-scope-badge', !formal && 'conv')}>
          {formal ? '任务正式成果 · 本任务共享' : '本会话产物'}
        </span>
        <span className="ap-ws-contract" title={artifactKey(artifact)}>
          {contractLabel(artifact.kind)} · {formatRelativeTime(artifact.updated_at)}
        </span>
        <div className="ap-ws-actions">
          {isTauri() && (
            <button type="button" onClick={handleReveal} className="ap-btn ghost">
              <FolderOpen />
              在文件夹中显示
            </button>
          )}
        </div>
      </div>
      <div className="ap-ws-body">
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
  )
}
