/**
 * 表格视图共用小件：文本单元格（「—」弱化）、编辑输入框、两步删除按钮、
 * 源码模式兜底提示条。两个视图（写作指引/承诺清单）同款交互，抽此处单源。
 */

import { useState } from 'react'
import { TriangleAlert, X } from 'lucide-react'
import { cn } from '@/lib/utils'

/** 查看态文本：「—」=空值弱化，其余原样（长词换行）。 */
export function CellText({ value, className }: { value: string; className?: string }) {
  const empty = !value || value === '—'
  return (
    <span className={cn('break-words leading-relaxed', empty && 'text-ink-3', className)}>{empty ? '—' : value}</span>
  )
}

/** 编辑态输入框（表格单元格内嵌；值原样含「—」，可全选替换）。 */
export function CellInput({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={cn(
        'w-full rounded-md border border-line bg-background px-2 py-1 text-sm outline-none',
        'focus:border-primary',
        className,
      )}
    />
  )
}

/**
 * 两步删除：首次点击变成「确认删除/取消」（行内、无浮层）。素材库审查教训
 * （删除无确认最痛）——删除行是可保存的破坏性操作，多一次确认。
 */
export function RowDelete({ onConfirm, hint }: { onConfirm: () => void; hint?: string }) {
  const [arming, setArming] = useState(false)
  if (!arming) {
    return (
      <button
        type="button"
        title={hint ?? '删除该行'}
        onClick={() => setArming(true)}
        className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-destructive"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    )
  }
  return (
    <span className="flex items-center gap-1 text-xs">
      <button
        type="button"
        onClick={onConfirm}
        className="rounded-md bg-destructive px-1.5 py-0.5 font-medium text-destructive-foreground hover:opacity-90"
      >
        确认删除
      </button>
      <button
        type="button"
        onClick={() => setArming(false)}
        className="rounded-md px-1.5 py-0.5 text-muted-foreground hover:bg-muted"
      >
        取消
      </button>
    </span>
  )
}

/** 源码模式兜底提示条（解析失败/用户主动切换时置顶说明）。 */
export function SourceFallbackNotice({ what }: { what: string }) {
  return (
    <div className="flex shrink-0 items-start gap-2 border-b border-warning/50 bg-warning/10 px-4 py-2 text-xs text-warning">
      <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>该文件不是标准{what}表（找不到唯一合法表格），已按 Markdown 源码模式打开。</span>
    </div>
  )
}
