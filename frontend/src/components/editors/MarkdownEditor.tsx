/**
 * markdown 统一编辑器（2026-09-04 编辑基建统一）：CodeMirror 6 源码栏 +
 * 实时预览分屏，三态布局（源码 / 分屏 / 预览）。笔记与工作台（以及将来的
 * 正文产物）共用；查看态 = viewOnly（只渲染预览栏）。
 *
 * - 源码栏：@uiw/react-codemirror + markdown 语言（语法高亮 / 行号 / 内建 undo）；
 *   主题经 .md-editor CSS 段消费设计 token（styles/workspace.css），dark 自动跟随；
 * - 预览栏：复用全站 ReactMarkdown 管线（GFM、单波浪关闭）；
 * - anchorLine：打开即切源码栏并滚动定位该行（来源追溯「查看原文上下文」用；
 *   选中即高亮，长文档不迷路）；同文件再定位（anchor 变化）同样响应；
 * - 行长封顶（2026-09-09）：查看类形态（viewOnly/readOnly/独占预览）文字列
 *   最宽 860px 居中（.md-prose-cap），中文长文舒适行长；可编辑源码/分屏吃满；
 * - 受控纪律：父组件负责「仅内容不同且无本地改动时才换 value」（防打断输入、
 *   防 undo 栈被重置）——本组件不做二次守卫。
 */

import { useEffect, useRef } from 'react'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import ReactMarkdown from 'react-markdown'
import { Eye, Columns2, Code } from 'lucide-react'
import { markdownComponents } from '@/components/ai/MemoMarkdown'
import { mdRemarkPlugins, stripCommentLines } from '@/lib/markdown'
import { cn } from '@/lib/utils'

export type EditorMode = 'source' | 'split' | 'preview'

const MODE_META: Array<{ mode: EditorMode; label: string; Icon: typeof Eye }> = [
  { mode: 'source', label: '源码', Icon: Code },
  { mode: 'split', label: '分屏', Icon: Columns2 },
  { mode: 'preview', label: '预览', Icon: Eye },
]

export function MarkdownEditor({
  value,
  onChange,
  mode,
  onModeChange,
  viewOnly = false,
  readOnly = false,
  anchorLine = null,
  placeholder,
  emptyLabel = '_（空文件）_',
  className,
}: {
  value: string
  onChange?: (v: string) => void
  mode: EditorMode
  onModeChange?: (m: EditorMode) => void
  viewOnly?: boolean
  /** 只读源码展示（parse/ 证据文件定位等）：源码栏不可编辑、无切换条 */
  readOnly?: boolean
  anchorLine?: number | null
  placeholder?: string
  emptyLabel?: string
  className?: string
}) {
  const cmRef = useRef<ReactCodeMirrorRef>(null)

  // anchor 定位：源码栏可见 + 滚动到行并选中（选中即高亮）
  useEffect(() => {
    if (anchorLine == null || viewOnly || (!readOnly && mode === 'preview')) return
    const view = cmRef.current?.view
    if (!view) return
    const line = Math.min(Math.max(anchorLine, 1), view.state.doc.lines)
    const pos = view.state.doc.line(line)
    view.dispatch({
      selection: { anchor: pos.from, head: pos.to },
      scrollIntoView: true,
    })
  }, [anchorLine, viewOnly, readOnly, mode])

  if (viewOnly) {
    return (
      <div className={cn('md-editor-preview prose-sm min-h-0 flex-1 overflow-auto', className)}>
        {/* 行长封顶在内层：滚动条留在面板缘，只有文字列居中收窄 */}
        <div className="md-prose-cap">
          <ReactMarkdown remarkPlugins={mdRemarkPlugins} components={markdownComponents}>
            {stripCommentLines(value) || emptyLabel}
          </ReactMarkdown>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('md-editor flex min-h-0 flex-1 flex-col gap-2', className)}>
      {onModeChange && !readOnly && (
        <div className="flex shrink-0 items-center gap-0.5 self-end rounded-md border border-line bg-card p-0.5">
          {MODE_META.map(({ mode: m, label, Icon }) => (
            <button
              key={m}
              type="button"
              onClick={() => onModeChange(m)}
              title={`${label}模式`}
              className={cn(
                'flex items-center gap-1 rounded px-1.5 py-0.5 text-xs',
                mode === m ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-3 w-3" />
              {label}
            </button>
          ))}
        </div>
      )}
      <div className="flex min-h-0 flex-1 gap-2">
        {mode !== 'preview' && (
          <CodeMirror
            ref={cmRef}
            value={value}
            onChange={(v) => onChange?.(v)}
            editable={!readOnly}
            extensions={[markdown()]}
            placeholder={placeholder}
            basicSetup={{ highlightActiveLine: !readOnly, foldGutter: false }}
            className={cn(
              'min-h-0 flex-1 overflow-hidden rounded-lg border border-line',
              // 只读源码=定位视图是「看」，同样收行长；可编辑源码/分屏吃满
              readOnly && 'md-prose-cap',
            )}
          />
        )}
        {mode !== 'source' && (
          <div
            className={cn(
              'md-editor-preview prose-sm min-h-0 flex-1 overflow-auto rounded-lg border border-line bg-card p-3',
              // 独占预览态收行长；分屏态每栏本就半宽不收
              mode === 'preview' && 'md-prose-cap',
            )}
          >
            <ReactMarkdown remarkPlugins={mdRemarkPlugins} components={markdownComponents}>
              {stripCommentLines(value) || emptyLabel}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}
