/**
 * 「关键事实与承诺」专用视图：`| 事项 | 值 | 说明 |` 三列结构化表格。
 *
 * 承诺清单是 AI 写正文时数字口径的唯一来源——列序锁定（dispatch_enrich 按位置
 * 取 cells[0]/cells[1]，列序错会读错值）。增删行自由；保存写回同一 md 文件
 * （useTableFile 全链：base_hash 冲突裁决/恢复点/「修订=用户」标记）。
 */

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { MarkdownEditor, type EditorMode } from '@/components/editors/MarkdownEditor'
import { FileEditorShell } from './FileEditorShell'
import { CellInput, CellText, RowDelete, SourceFallbackNotice } from './tableBits'
import { useTableFile } from './useTableFile'
import { PROMISE_TABLE } from '@/lib/workbenchTable'

export function PromiseFileView({ taskId, path }: { taskId: string | null; path: string | null }) {
  const file = useTableFile({ taskId, path, spec: PROMISE_TABLE })
  const [editorMode, setEditorMode] = useState<EditorMode>('split')

  if (!path || !taskId) return null
  if (file.loading || (!file.text && file.loadError)) {
    return (
      <div className="ap-ws">
        <div className="ap-ws-body">
          <div className="p-6 text-center text-sm text-muted-foreground">
            {file.loading ? '加载工作台文件…' : `加载失败：${file.loadError}`}
          </div>
        </div>
      </div>
    )
  }

  const cols = PROMISE_TABLE.columns
  const setCell = (row: number, col: number, v: string) => {
    file.applyRows(file.rows.map((r, i) => (i === row ? r.map((c, k) => (k === col ? v : c)) : r)))
  }

  return (
    <FileEditorShell
      title="关键事实与承诺"
      file={file}
      notice={!file.tableMode ? <SourceFallbackNotice what="「事项｜值｜说明」" /> : undefined}
    >
      {file.tableMode ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <p className="shrink-0 text-xs leading-relaxed text-muted-foreground">
            承诺值是 AI 写正文时数字与口径的唯一来源（工期/人员/服务/报价口径）——改动保存后，
            后续正文按改后的值执行；删除行 = AI 不再带这条承诺（缺项会写【待澄清】）。
          </p>
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line-2 text-left text-xs text-muted-foreground">
                {cols.map((c) => (
                  <th key={c} className="px-2 py-2 font-medium">
                    {c}
                  </th>
                ))}
                {file.editing && <th className="w-24 px-2 py-2 font-medium">操作</th>}
              </tr>
            </thead>
            <tbody>
              {file.rows.map((r, i) => (
                <tr key={i} className="border-b border-line/60 align-top hover:bg-muted/30">
                  {cols.map((c, k) => (
                    <td key={c} className={cn('px-2 py-1.5', k === 0 && 'font-medium')}>
                      {file.editing ? (
                        <CellInput
                          value={r[k] ?? ''}
                          onChange={(v) => setCell(i, k, v)}
                          placeholder={k === 0 ? '事项（如：免费维护期）' : k === 1 ? '值（如：3 年）' : '说明（可空）'}
                        />
                      ) : (
                        <CellText value={r[k] ?? ''} />
                      )}
                    </td>
                  ))}
                  {file.editing && (
                    <td className="px-2 py-1.5">
                      <RowDelete
                        hint="删除后 AI 写正文不再带这条承诺"
                        onConfirm={() => file.applyRows(file.rows.filter((_r, j) => j !== i))}
                      />
                    </td>
                  )}
                </tr>
              ))}
              {file.rows.length === 0 && (
                <tr>
                  <td colSpan={cols.length + (file.editing ? 1 : 0)} className="px-2 py-6 text-center text-xs text-muted-foreground">
                    清单为空——AI 派发写手时会把缺项一律写【待澄清】。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {file.editing && (
            <button
              type="button"
              onClick={() => file.applyRows([...file.rows, ['', '', '']])}
              className="w-fit rounded-md border border-line px-3 py-1.5 text-xs text-muted-foreground hover:border-primary hover:text-foreground"
            >
              + 添加事项
            </button>
          )}
        </div>
      ) : (
        // 源码模式兜底（解析失败或用户主动切换）
        file.editing ? (
          <MarkdownEditor value={file.text} onChange={file.editSource} mode={editorMode} onModeChange={setEditorMode} />
        ) : (
          <MarkdownEditor value={file.text} mode="preview" viewOnly className="prose-sm" />
        )
      )}
    </FileEditorShell>
  )
}
