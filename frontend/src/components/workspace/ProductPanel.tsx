import { useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Maximize2, Minimize2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface ArtifactRow {
  name: string
  /** md-ico 徽标首字符（如 "M"） */
  mark: string
}

export interface ProductPanelProps {
  artifacts?: ArtifactRow[]
  width?: number
  defaultCollapsed?: boolean
  onCollapse?: (collapsed: boolean) => void
  onOpen?: (name: string) => void
}

const MIN_W = 240
const MAX_W = 560

/** 右栏产物面板：可折叠 + 可拖拽调宽；头部含放大/缩小 + chevron。 */
export function ProductPanel({
  artifacts = [],
  width: initialWidth = 300,
  defaultCollapsed = false,
  onCollapse,
  onOpen,
}: ProductPanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  const [width, setWidth] = useState(initialWidth)
  const appRect = useRef<DOMRect | null>(null)

  const toggle = () => {
    setCollapsed((v) => {
      onCollapse?.(!v)
      return !v
    })
  }

  const resizeBy = (delta: number) => setWidth((w) => Math.min(MAX_W, Math.max(MIN_W, w + delta)))

  return (
    <>
      <aside
        className={cn('product', collapsed && 'collapsed')}
        style={collapsed ? undefined : { width }}
      >
        <div
          className="resizer"
          onMouseDown={(e) => {
            if (collapsed) return
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
        <div className="product-head" onClick={toggle}>
          <div className="panel-actions">
            <button
              type="button"
              className="panel-btn"
              title="放大"
              onClick={(e) => {
                e.stopPropagation()
                resizeBy(60)
              }}
            >
              <Maximize2 />
            </button>
            <button
              type="button"
              className="panel-btn"
              title="缩小"
              onClick={(e) => {
                e.stopPropagation()
                resizeBy(-60)
              }}
            >
              <Minimize2 />
            </button>
          </div>
          <ChevronDown className="product-chev" />
          <span>产物</span>
        </div>
        <div className="product-body">
          {artifacts.map((a) => (
            <div className="artifact" key={a.name} onClick={() => onOpen?.(a.name)}>
              <span className="md-ico">{a.mark.charAt(0).toUpperCase()}</span>
              <span className="name truncate">{a.name}</span>
            </div>
          ))}
        </div>
      </aside>
      <button type="button" className="product-toggle" title="展开产物面板" onClick={toggle}>
        <ChevronRight />
      </button>
    </>
  )
}
