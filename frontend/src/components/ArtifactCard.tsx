import { Braces, File, FileText, FolderOpen, Globe } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { isTauri, revealInFolder } from '@/api/client'
import { formatSize, cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

/** §6 类型图标：html=🌐(Globe)、json=🧾(Braces/FileJson)、md=📝(FileText)。 */
const typeIcon: Record<Artifact['type'], LucideIcon> = {
  html: Globe,
  json: Braces,
  md: FileText,
  other: File,
}

/** §6 产物卡：整卡可点击打开预览；hover 显示「在文件夹中显示」图标按钮。 */
export function ArtifactCard({ artifact, onOpen }: { artifact: Artifact; onOpen: (id: string) => void }) {
  const Icon = typeIcon[artifact.type] ?? FileText
  const { toast } = useToast()

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
      className="group flex w-full cursor-pointer items-center gap-3 rounded-xl border bg-card px-3 py-2.5 transition-colors hover:border-primary"
      onClick={() => onOpen(artifact.id)}
    >
      <Icon className="h-5 w-5 shrink-0 text-primary" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={artifact.name}>
          {artifact.name}
        </p>
        <p className="text-xs text-muted-foreground">
          {formatSize(artifact.size)} · {artifact.type} · 点击预览
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
