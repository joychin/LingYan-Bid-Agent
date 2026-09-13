/**
 * 结构化表格文件的查看/编辑外壳（写作指引/承诺清单两个视图共用）：
 * 头部（标题 + 保存状态 + 表格/源码切换 + 编辑/完成 + 恢复上一版）+ 冲突横幅 +
 * 自定义提示条 + 内容区。保存/冲突/恢复语义全部来自 useTableFile——本组件纯展示。
 * 有意不反向重构 WorkbenchViewer（行数漂移闸是它特有的），模式搬自其头部。
 */

import type { ReactNode } from 'react'
import { History, Pencil, Table2, FileCode } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SaveStateBar } from '@/components/editors/SaveStateBar'
import type { TableFileHandle } from './useTableFile'

export function FileEditorShell({
  title,
  file,
  badges,
  notice,
  contentClassName,
  children,
}: {
  title: string
  file: TableFileHandle
  /** 标题右侧的额外徽章（如「缺素材 N 节」统计） */
  badges?: ReactNode
  /** 冲突横幅之下的自定义提示条（如源码模式兜底说明） */
  notice?: ReactNode
  /** 内容区容器类名（缺省=单栏滚动）。两栏视图传 overflow-hidden 去 padding，
   *  由内部分栏各自滚动。 */
  contentClassName?: string
  children: ReactNode
}) {
  const { auto, editing, editable, hasRestore, tableMode } = file

  return (
    <div className="ap-ws">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b pl-4 pr-[88px] py-3">
        <span className="truncate text-sm font-semibold">{title}</span>
        <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-muted-foreground">工作台</span>
        {file.revised && (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">已人工修订</span>
        )}
        {badges}
        <div className="ml-auto flex items-center gap-1">
          {editing && <SaveStateBar state={auto.state} lastSavedAt={auto.lastSavedAt} onRetry={() => void auto.saveNow()} />}
          {/* 表格/源码双模式（同 DocxView 版式/文本切换的逃生口纪律） */}
          <div className="flex items-center rounded-md border border-line p-0.5">
            <button
              type="button"
              title="结构化表格"
              onClick={file.enableTableMode}
              disabled={tableMode}
              className={cn(
                'flex items-center gap-1 rounded px-1.5 py-0.5 text-xs',
                tableMode ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <Table2 className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Markdown 源码"
              onClick={file.enableSourceMode}
              disabled={!tableMode}
              className={cn(
                'flex items-center gap-1 rounded px-1.5 py-0.5 text-xs',
                !tableMode ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <FileCode className="h-3.5 w-3.5" />
            </button>
          </div>
          {editable && !editing && (
            <button
              type="button"
              onClick={file.startEdit}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Pencil className="h-3.5 w-3.5" />
              编辑
            </button>
          )}
          {editable && hasRestore && !editing && (
            <button
              type="button"
              onClick={() => void file.restore()}
              title="当前内容自动入恢复点栈（保留 3 个），可再次恢复撤销"
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <History className="h-3.5 w-3.5" />
              恢复上一版
            </button>
          )}
          {editable && editing && (
            <button
              type="button"
              onClick={file.finishEdit}
              className="rounded-md bg-inverse px-2.5 py-1 text-xs text-primary-foreground hover:opacity-90"
            >
              完成编辑
            </button>
          )}
        </div>
      </div>

      {auto.state === 'conflict' && (
        <div className="border-b border-warning/50 bg-warning/10 px-4 py-2 text-xs text-warning">
          <div className="flex flex-wrap items-center gap-3">
            <span>文件已被其他修改更新（可能是模型重跑），你的本地改动与其冲突。</span>
            <button type="button" className="underline" onClick={() => void file.adoptLatest()}>
              拉取最新内容
            </button>
            <button type="button" className="underline" onClick={() => void auto.saveNow(true)}>
              保留我的版本
            </button>
          </div>
        </div>
      )}
      {notice}

      {/* 两栏视图传 contentClassName 覆盖默认单栏滚动容器（overflow-auto + p-4 与
          overflow-hidden 属同类工具类，靠类名顺序赢不了——必须整串替换） */}
      <div className={cn('flex min-h-0 flex-1 flex-col', contentClassName ?? 'overflow-auto p-4')}>{children}</div>
    </div>
  )
}
