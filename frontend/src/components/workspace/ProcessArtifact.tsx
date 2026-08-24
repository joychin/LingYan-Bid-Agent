import type { ReactNode } from 'react'
import { ChevronDown, CornerDownRight, Lightbulb, PenLine, Search, SquareCheckBig } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ArtifactVariant = 'thinking' | 'tool' | 'todo' | 'search' | 'edit'

const DEFAULT_LABEL: Record<ArtifactVariant, string> = {
  thinking: '深度思考',
  tool: '工具调用',
  todo: '任务清单',
  search: '已搜索',
  edit: '编辑文件',
}

const VAR_ICON: Record<ArtifactVariant, typeof Lightbulb> = {
  thinking: Lightbulb,
  tool: CornerDownRight,
  todo: SquareCheckBig,
  search: Search,
  edit: PenLine,
}

export interface ProcessArtifactProps {
  variant: ArtifactVariant
  label?: string
  /** 右侧 meta（状态、计数、spinner 等） */
  meta?: ReactNode
  open?: boolean
  icon?: ReactNode
  className?: string
  children?: ReactNode
}

/** 过程产物折叠块（details）：thinking / tool / todo / search / edit 五变体。 */
export function ProcessArtifact({
  variant,
  label,
  meta,
  open = true,
  icon,
  className,
  children,
}: ProcessArtifactProps) {
  const Icon = VAR_ICON[variant]
  return (
    <details className={cn('art', variant, className)} open={open}>
      <summary>
        {icon ?? <Icon className="art-ico" />}
        <span className="art-label">{label ?? DEFAULT_LABEL[variant]}</span>
        {meta && <span className="art-meta">{meta}</span>}
        <ChevronDown className="art-chev" />
      </summary>
      {children && <div className="art-body">{children}</div>}
    </details>
  )
}

export type TodoStatus = 'done' | 'doing' | 'pending'

export interface TodoRow {
  status: TodoStatus
  content: string
}

/** 任务清单列表（todo 变体 body）：✓ / ● / 空 三态。 */
export function TodoList({ items }: { items: TodoRow[] }) {
  return (
    <ul className="todo">
      {items.map((t, i) => (
        <li key={i} className={cn(t.status === 'done' && 'done', t.status === 'doing' && 'doing')}>
          <span className="chk">{t.status === 'done' ? '✓' : t.status === 'doing' ? '●' : ''}</span>
          {t.content}
        </li>
      ))}
    </ul>
  )
}

/** 执行中 spinner（tool/thinking 的 meta 用）。 */
export function Spinner() {
  return <span className="spinner" />
}

/** 深度思考的脉冲圆点。 */
export function ArtPulse() {
  return <span className="art-dot" />
}
