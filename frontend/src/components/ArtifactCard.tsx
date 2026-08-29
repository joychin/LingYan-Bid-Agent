import { useState } from 'react'
import { FileText, FolderOpen } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { isTauri, revealInFolder } from '@/api/client'
import { contractLabel, kindIcon } from '@/artifacts/registry'
import { formatRelativeTime, cn } from '@/lib/utils'
import { PromoteConfirmModal } from '@/components/PromoteConfirmModal'
import { useToast } from '@/context/Toast'

/** 聊天内产物卡：整卡可点击打开对应 Processor（v3：面板工作区态）。
 *  过程稿带「转正」入口 → PromoteConfirmModal 确认（带 content_seq，409 软确认）。
 *  图标与右侧产物面板共用 kindIcon 语义色板（registry.kindIcon）。 */
export function ArtifactCard({ artifact, onOpen }: { artifact: Artifact; onOpen: (id: string) => void }) {
  const { toast } = useToast()
  const [confirming, setConfirming] = useState(false)
  const icon = kindIcon(artifact.kind)
  const formal = artifact.scope === 'task'

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
        artifact.promotion_proposed ? 'border-warning/60 hover:border-warning' : 'hover:border-primary',
      )}
      onClick={() => onOpen(artifact.artifact_id)}
    >
      {icon ? (
        <span className={cn('ft-ico ft-ico--card', icon.cls)}>{icon.mark}</span>
      ) : (
        <FileText className="h-5 w-5 shrink-0 text-muted-foreground" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="truncate text-sm font-medium" title={artifact.display_name}>
            {artifact.display_name}
          </p>
          {artifact.promotion_proposed && (
            <span className="shrink-0 rounded-full bg-warning/15 px-1.5 py-px text-[10px] font-medium text-warning">
              AI 建议转正
            </span>
          )}
          {formal && (
            <span className="shrink-0 rounded-full bg-accent-soft px-1.5 py-px text-[10px] font-medium text-muted-foreground">
              任务正式成果
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {contractLabel(artifact.kind)} · 更新于 {formatRelativeTime(artifact.updated_at)}
        </p>
      </div>
      {!formal && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setConfirming(true)
          }}
          className={cn(
            'flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors',
            artifact.promotion_proposed
              ? 'bg-warning/15 text-warning hover:bg-warning/25'
              : 'text-muted-foreground hover:bg-accent hover:text-foreground',
          )}
          title="复制到任务项目文件（原件保留，覆盖自动留恢复点）"
        >
          转为正式成果
        </button>
      )}
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
      <PromoteConfirmModal artifact={confirming ? artifact : null} onClose={() => setConfirming(false)} />
    </div>
  )
}
