import { FileText, FolderOpen } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { isTauri, revealInFolder } from '@/api/client'
import { contractLabel, kindIcon } from '@/artifacts/registry'
import { formatRelativeTime, cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

/** 聊天内产物卡：整卡可点击打开对应 Processor（v3：面板工作区态）。
 *  图标与右侧产物面板共用 kindIcon 语义色板（registry.kindIcon）。 */
export function ArtifactCard({ artifact, onOpen }: { artifact: Artifact; onOpen: (id: string) => void }) {
  const { toast } = useToast()
  const icon = kindIcon(artifact.kind)

  const handleReveal = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await revealInFolder(artifact.path)
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), 'error')
    }
  }

  return (
    <div
      className={cn(
        'group flex w-full cursor-pointer items-center gap-3 rounded-xl border bg-card px-3 py-2.5 transition-colors',
        'hover:border-primary',
      )}
      onClick={() => onOpen(artifact.artifact_id)}
    >
      {icon ? (
        <span className={cn('ft-ico ft-ico--card', icon.cls)}>{icon.mark}</span>
      ) : (
        <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={artifact.display_name}>
          {artifact.display_name}
        </p>
        <p className="text-xs text-muted-foreground">
          {contractLabel(artifact.kind)} · 更新于 {formatRelativeTime(artifact.updated_at)}
        </p>
      </div>
      {isTauri() && (
        <button
          type="button"
          onClick={handleReveal}
          className={cn(
            'hidden shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground group-hover:block',
          )}
          title="在文件夹中显示"
        >
          <FolderOpen className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
