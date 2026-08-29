/**
 * 工作台查看/编辑器：out/ 过程产物（md）的模态查看 + 源码编辑。
 *
 * 编辑走「探测 + 用户裁决 + 恢复点兜底」（设计铁则）：
 * - 保存带 base_hash 乐观探测，409 = 模型重跑过 → amber 横幅「拉取最新 / 保留我的」；
 * - 编辑期间 5s 轮询远端 hash：无本地改动静默跟随、有则弹横幅（DirectoryProcessor 先例）；
 * - 「恢复上一版」与 .bak 互换（服务端），恢复本身可再撤销；
 * - 机器输入三文件（business/format/evaluation）保存时行数变化 → 编号漂移确认（提示不阻止，
 *   一次编辑会话只确认一次——两个按钮都视为已确认，避免防抖自动保存反复弹）；
 * - 服务端保存成功会盖「修订=用户」头标记（头部徽章可见，模型重跑前的提示线索）。
 * parse/ 只读（引用行号的证据基准）；「存为笔记」把当前内容快照发布为 doc.note 过程稿。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { History, Loader2, NotebookPen, Pencil, X } from 'lucide-react'
import {
  getWorkbenchContent,
  putWorkbenchContent,
  restoreWorkbench,
  saveWorkbenchNote,
} from '@/api/client'
import { markdownComponents } from '@/components/ChatMessage'
import { mdRemarkPlugins } from '@/lib/markdown'
import { useToast } from '@/context/Toast'

/** REQ/MAND/TPL/SCORE 登记表所在文件：行序=编号，增删行会整体漂移（assemble 解析协议）。 */
const MACHINE_INPUTS = ['analysis/requirements-business.md', 'analysis/requirements-format.md', 'analysis/evaluation.md']

/** 解析首行头部注释（<!-- … | 生成=… | 修订=用户 … -->）成键值对徽章。 */
function parseHeader(content: string): Record<string, string> {
  const first = content.split('\n')[0] ?? ''
  const m = first.match(/^<!--\s*(.*?)\s*-->$/)
  const out: Record<string, string> = {}
  if (!m) return out
  for (const part of m[1].split('|')) {
    const idx = part.indexOf('=')
    if (idx > 0) out[part.slice(0, idx).trim()] = part.slice(idx + 1).trim()
  }
  return out
}

/** 表格行数（数据行；分隔行 `|---|` 与表头计法一致即可作漂移探测）。 */
function tableRows(text: string): number {
  return text.split('\n').filter((l) => l.startsWith('|') && !/^\|\s*[-:]/.test(l)).length
}

export function WorkbenchViewer({
  taskId,
  conversationId,
  path,
  onClose,
}: {
  taskId: string | null
  conversationId: string | null
  path: string | null
  onClose: () => void
}) {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [conflict, setConflict] = useState(false)
  const [rowWarn, setRowWarn] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<'saved' | 'saving' | 'error' | null>(null)

  const dirtyRef = useRef(false)
  const conflictRef = useRef(false)
  const rowWarnRef = useRef(false)
  const rowsConfirmedRef = useRef(false)
  const savingRef = useRef(false)
  const timerRef = useRef<number | null>(null)
  const pollRef = useRef<number | null>(null)
  const hashRef = useRef('')
  const baseRowsRef = useRef(0)
  const latest = useRef({ text: '', hash: '' })
  latest.current = { text, hash: hashRef.current }

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['workbench', taskId, 'content', path],
    queryFn: async () => await getWorkbenchContent(taskId!, path!),
    enabled: !!taskId && !!path,
  })

  // 切换文件：整体重置编辑态（只在 path 变化时；data 刷新不打断编辑）
  useEffect(() => {
    setEditing(false)
    setConflict(false)
    setRowWarn(false)
    setStatus(null)
    dirtyRef.current = false
    conflictRef.current = false
    rowWarnRef.current = false
    rowsConfirmedRef.current = false
  }, [path])

  // 内容同步：无本地改动时跟随服务端（首次加载与外部更新后的静默跟随）
  useEffect(() => {
    if (!data || dirtyRef.current) return
    setText(data.content)
    hashRef.current = data.hash
    baseRowsRef.current = tableRows(data.content)
  }, [data])

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['workbench', taskId] })
  }, [queryClient, taskId])

  const doSave = useCallback(
    async (force = false): Promise<boolean> => {
      if (!taskId || !path || savingRef.current) return false
      // 机器输入文件：行数变化且本次会话未确认过 → 先弹确认（提示不阻止）
      if (
        !force &&
        !rowsConfirmedRef.current &&
        MACHINE_INPUTS.includes(path) &&
        tableRows(latest.current.text) !== baseRowsRef.current
      ) {
        rowWarnRef.current = true
        setRowWarn(true)
        setStatus(null)
        return false
      }
      savingRef.current = true
      setSaving(true)
      setStatus('saving')
      try {
        const res = await putWorkbenchContent(taskId, path, latest.current.text, hashRef.current, force)
        hashRef.current = res.hash
        baseRowsRef.current = tableRows(latest.current.text)
        dirtyRef.current = false
        setStatus('saved')
        setConflict(false)
        conflictRef.current = false
        invalidate()
        return true
      } catch (e) {
        const err = e as Error & { status?: number }
        if (err.status === 409) {
          setConflict(true)
          conflictRef.current = true
          setStatus(null)
        } else {
          setStatus('error')
        }
        return false
      } finally {
        savingRef.current = false
        setSaving(false)
      }
    },
    [taskId, path, invalidate],
  )

  const adoptLatest = useCallback(async () => {
    if (!taskId || !path) return
    const fresh = await getWorkbenchContent(taskId, path)
    setText(fresh.content)
    hashRef.current = fresh.hash
    baseRowsRef.current = tableRows(fresh.content)
    dirtyRef.current = false
    setConflict(false)
    conflictRef.current = false
    setStatus(null)
    setRowWarn(false)
    rowWarnRef.current = false
    rowsConfirmedRef.current = false
  }, [taskId, path])

  // 编辑期间：800ms 防抖自动保存 + 5s 轮询远端 hash（模型重跑探测）
  useEffect(() => {
    if (!editing || !taskId || !path) return
    timerRef.current = window.setInterval(() => {
      if (dirtyRef.current && !conflictRef.current && !savingRef.current && !rowWarnRef.current) void doSave()
    }, 800)
    pollRef.current = window.setInterval(() => {
      if (savingRef.current || conflictRef.current) return
      getWorkbenchContent(taskId, path)
        .then((fresh) => {
          if (fresh.hash === hashRef.current) return
          if (dirtyRef.current) {
            setConflict(true)
            conflictRef.current = true
          } else {
            void adoptLatest()
          }
        })
        .catch(() => {})
    }, 5_000)
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current)
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [editing, taskId, path, doSave, adoptLatest])

  // 卸载冲刷：dirty 未存 → 尝试保存，失败强制保留用户版（NoteProcessor 先例）
  useEffect(() => {
    return () => {
      if (dirtyRef.current && taskId && path) {
        void putWorkbenchContent(taskId, path, latest.current.text, hashRef.current, false).catch(() => {
          void putWorkbenchContent(taskId, path, latest.current.text, hashRef.current, true).catch(() => {})
        })
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!path || !taskId) return null
  if (!data) {
    return (
      <div className="ap-ws">
        <div className="ap-ws-body">
          <div className="p-6 text-center text-sm text-muted-foreground">
            {isLoading ? '加载工作台文件…' : isError ? `加载失败：${error instanceof Error ? error.message : String(error)}` : ''}
          </div>
        </div>
      </div>
    )
  }

  const header = parseHeader(data.content)
  const display = path.split('/').pop() ?? path
  const editable = data.editable

  const finishEdit = () => {
    if (conflict) {
      toast('请先裁决：拉取最新或保留我的版本', 'error')
      return
    }
    if (dirtyRef.current) void doSave()
    setEditing(false)
  }

  const handleRestore = async () => {
    if (!taskId || !path) return
    try {
      const res = await restoreWorkbench(taskId, path)
      setText(res.content)
      hashRef.current = res.hash
      dirtyRef.current = false
      setEditing(false)
      setConflict(false)
      conflictRef.current = false
      rowWarnRef.current = false
      rowsConfirmedRef.current = false
      invalidate()
      toast('已恢复上一版（可再次恢复撤销）', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  const handleNote = async () => {
    if (!conversationId || !path) return
    try {
      const res = await saveWorkbenchNote(conversationId, path)
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      toast(`已存为笔记「${res.display_name}」到会话产物`, 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <div className="ap-ws">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-3">
        <span className="truncate text-sm font-semibold">{display}</span>
        <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-muted-foreground">工作台</span>
        {header['主文件'] && (
          <span className="max-w-40 truncate text-xs text-muted-foreground" title={header['主文件']}>
            来源：{header['主文件']}
          </span>
        )}
        {header['生成'] && <span className="text-xs text-muted-foreground">生成 {header['生成'].slice(5, 16)}</span>}
        {(data.revised || header['修订']) && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">已人工修订</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          {status === 'saved' && <span className="text-xs text-muted-foreground">已保存</span>}
          {status === 'error' && (
            <button type="button" className="text-xs text-red-600 hover:underline" onClick={() => void doSave()}>
              保存失败 · 点击重试
            </button>
          )}
          {editable && !editing && (
            <button
              type="button"
              onClick={() => {
                setEditing(true)
                baseRowsRef.current = tableRows(text)
              }}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <Pencil className="h-3.5 w-3.5" />
              编辑
            </button>
          )}
          {editable && data.has_backup && !editing && (
            <button
              type="button"
              onClick={() => void handleRestore()}
              title="覆盖前自动留底，可再次恢复撤销"
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <History className="h-3.5 w-3.5" />
              恢复上一版
            </button>
          )}
          <button
            type="button"
            onClick={() => void handleNote()}
            disabled={!conversationId}
            title={conversationId ? '把当前内容快照发布为会话产物笔记（不再随后续重跑变化）' : '需要会话上下文'}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
          >
            <NotebookPen className="h-3.5 w-3.5" />
            存为笔记
          </button>
          {editing && (
            <button
              type="button"
              onClick={finishEdit}
              className="rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground hover:opacity-90"
            >
              完成编辑
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {(conflict || rowWarn) && (
        <div className="border-b bg-amber-50 px-4 py-2 text-xs text-amber-800">
          {conflict ? (
            <div className="flex flex-wrap items-center gap-3">
              <span>文件已被其他修改更新（可能是模型重跑），你的本地改动与其冲突。</span>
              <button type="button" className="underline" onClick={() => void adoptLatest()}>
                拉取最新内容
              </button>
              <button type="button" className="underline" onClick={() => void doSave(true)}>
                保留我的版本
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <span>检测到表格行数变化：行序=编号（REQ/MAND/SCORE），增删行使编号整体漂移、下游目录引用可能悬空。</span>
              <button
                type="button"
                className="underline"
                onClick={() => {
                  rowsConfirmedRef.current = true
                  rowWarnRef.current = false
                  setRowWarn(false)
                  void doSave()
                }}
              >
                仍要保存
              </button>
              <button
                type="button"
                className="underline"
                onClick={() => {
                  rowsConfirmedRef.current = true
                  rowWarnRef.current = false
                  setRowWarn(false)
                }}
              >
                返回修改
              </button>
            </div>
          )}
        </div>
      )}

      <div className="flex-1 overflow-auto p-4">
        {editing ? (
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              dirtyRef.current = true
            }}
            spellCheck={false}
            className="h-full w-full resize-none rounded-md border bg-background p-3 font-mono text-[13px] leading-relaxed outline-none focus:ring-1 focus:ring-ring"
          />
        ) : (
          <div className="prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={mdRemarkPlugins} components={markdownComponents}>
              {text || '_（空文件）_'}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}
