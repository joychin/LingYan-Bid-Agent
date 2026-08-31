import { useState } from 'react'
import { FileText, FolderOpen } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { isTauri, revealInFolder } from '@/api/client'
import { contractLabel, kindIcon } from '@/artifacts/registry'
import { formatRelativeTime, cn } from '@/lib/utils'
import { ConfirmModal } from '@/components/ConfirmModal'
import { useToast } from '@/context/Toast'

/** 聊天内产物卡：整卡可点击打开对应 Processor（v3：面板工作区态）。
 *  草稿带「确认」入口 → ConfirmModal（带 content_seq，409 软确认）；已确认显示徽章。
 *  图标与右侧产物面板共用 kindIcon 语义色板（registry.kindIcon）。 */
export function ArtifactCard({ artifact, onOpen }: { artifact: Artifact; onOpen: (id: string) => void }) {
  const { toast } = useToast()
  const [confirming, setConfirming] = useState(false)
  const icon = kindIcon(artifact.kind)
  const confirmed = artifact.state === 'confirmed'

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
        <div className="flex items-center gap-1.5">
          <p className="truncate text-sm font-medium" title={artifact.display_name}>
            {artifact.display_name}
          </p>
          {confirmed && (
            <span className="shrink-0 rounded-full bg-accent-soft px-1.5 py-px text-[10px] font-medium text-muted-foreground">
              正式成果
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {contractLabel(artifact.kind)} · 更新于 {formatRelativeTime(artifact.updated_at)}
        </p>
      </div>
      {!confirmed && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setConfirming(true)
          }}
          className={cn(
            'flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors',
            'text-muted-foreground hover:bg-accent hover:text-foreground',
          )}
          title="确认为正式成果（不复制，可撤销；AI 重跑覆盖会降回草稿）"
        >
          确认
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
      <ConfirmModal artifact={confirming ? artifact : null} onClose={() => setConfirming(false)} />
    </div>
  )
}
