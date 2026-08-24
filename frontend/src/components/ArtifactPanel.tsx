import { useRef, useState } from 'react'
import { ChevronRight, Folder, FolderOpen, Maximize2, Minimize2 } from 'lucide-react'
import type { Artifact } from '@/api/client'
import { isTauri, revealInFolder } from '@/api/client'
import { useArtifacts } from '@/hooks/useArtifacts'
import { useFileUpload } from '@/context/FileUpload'
import { formatRelativeTime, cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

const TYPE_MARK: Record<Artifact['type'], string> = {
  html: 'H',
  json: 'J',
  md: 'M',
  other: 'F',
}

const DEFAULT_W = 300
const MIN_W = 240
const MAX_W = 560

/** Workspace 右栏产物面板：可折叠 + 可拖拽调宽；teal 徽标行 + 当前会话圆点 + hover「在文件夹中显示」。 */
export function ArtifactPanel({
  currentConvId,
  collapsed,
  onOpen,
  onCollapse,
}: {
  currentConvId: string | null
  collapsed: boolean
  onOpen: (id: string) => void
  onCollapse: () => void
}) {
  const { data: artifacts = [], isLoading } = useArtifacts()
  const { openFilePicker } = useFileUpload()
  const { toast } = useToast()
  const [width, setWidth] = useState(DEFAULT_W)
  const [expanded, setExpanded] = useState(false)
  const [closing, setClosing] = useState(false)
  const appRect = useRef<DOMRect | null>(null)

  const handleCollapseToggle = () => {
    setExpanded(false)
    setClosing(false)
    setWidth(DEFAULT_W)
    onCollapse()
  }

  const handleExpandToggle = () => {
    if (expanded) {
      // 先播放抽屉滑出动画，结束后回到右侧 dock
      setClosing(true)
      window.setTimeout(() => {
        setExpanded(false)
        setClosing(false)
        setWidth(DEFAULT_W)
      }, 260)
    } else {
      setExpanded(true)
    }
  }

  const handleReveal = async (a: Artifact) => {
    try {
      await revealInFolder(a.path)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <>
      <aside
        className={cn('product', collapsed && 'collapsed', expanded && 'expanded', closing && 'closing')}
        style={collapsed || expanded ? undefined : { width }}
      >
        <div
          className="resizer"
          onMouseDown={(e) => {
            if (collapsed || expanded) return
            appRect.current = e.currentTarget.closest('.app')?.getBoundingClientRect() ?? null
            const onMove = (ev: MouseEvent) => {
              if (!appRect.current) return
              setWidth(Math.max(MIN_W, Math.min(MAX_W, appRect.current.right - ev.clientX)))
            }
            const onUp = () => {
              window.removeEventListener('mousemove', onMove)
              window.removeEventListener('mouseup', onUp)
            }
            window.addEventListener('mousemove', onMove)
            window.addEventListener('mouseup', onUp)
          }}
        />
        <div className="product-head" onClick={handleCollapseToggle}>
          <div className="panel-actions">
            <button
              type="button"
              className="panel-btn"
              title={expanded ? '缩小' : '放大'}
              onClick={(e) => {
                e.stopPropagation()
                handleExpandToggle()
              }}
            >
              {expanded ? <Minimize2 /> : <Maximize2 />}
            </button>
          </div>
          {!isLoading && artifacts.length > 0 && (
            <span className="ml-auto text-xs text-muted-foreground">{artifacts.length}</span>
          )}
        </div>
        <div className="product-body">
          {isLoading && <p className="py-4 text-center text-xs text-muted-foreground">加载产物…</p>}
          {!isLoading && artifacts.length === 0 && <EmptyState onUpload={openFilePicker} />}
          {artifacts.map((a) => {
            const isCurrent = a.conversation_id === currentConvId
            return (
              <div key={a.id} className="artifact group" onClick={() => onOpen(a.id)}>
                <span
                  className={cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    isCurrent ? 'bg-primary' : 'bg-transparent',
                  )}
                />
                <span className="md-ico">{TYPE_MARK[a.type] ?? 'F'}</span>
                <div className="min-w-0 flex-1">
                  <div className="name truncate">{a.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {a.type.toUpperCase()} · {formatRelativeTime(a.created_at)}
                  </div>
                </div>
                {isTauri() && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      void handleReveal(a)
                    }}
                    className="hidden shrink-0 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground group-hover:block"
                    title="在文件夹中显示"
                  >
                    <FolderOpen className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </aside>
      <button type="button" className="product-toggle" title="展开产物面板" onClick={handleCollapseToggle}>
        <ChevronRight />
      </button>
    </>
  )
}

function EmptyState({ onUpload }: { onUpload: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center">
      <Folder className="h-8 w-8 text-ink-3" strokeWidth={1.5} />
      <p className="text-sm text-muted-foreground">还没有产物</p>
      <p className="text-xs text-muted-foreground">上传一份招标文件，让 Agent 生成目录规划</p>
      <button
        type="button"
        onClick={onUpload}
        className="mt-2 rounded-md border border-line bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:border-line-2 hover:shadow"
      >
        上传文件
      </button>
    </div>
  )
}
