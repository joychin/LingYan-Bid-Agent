/**
 * 工作台查看/编辑器：work/ 过程产物（md）的查看 + 源码编辑。
 *
 * 保存基建走 useAutoSave（2026-09-04 统一）：防抖自动保存 + base_hash 乐观探测
 * （409 = 模型重跑过 → 横幅「拉取最新 / 保留我的」）+ 5s 轻量探测（meta 端点只比哈希）。
 * - 机器输入三文件（business/format/evaluation）保存前行数变化 → 编号漂移确认
 *   （beforeSave 闸拦截：不发起保存、保持 dirty；提示不阻止，一次编辑会话只确认一次）；
 * - 恢复上一版 = 当前内容先入恢复点栈（保留 3 个），可再次恢复撤销；
 * - 服务端保存成功会盖「修订=用户」首行注释（「已人工修订」徽章可见，模型重跑前的提示线索）。
 * parse/ 只读（引用行号的证据基准）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, History, Pencil } from 'lucide-react'
import {
  getWorkbenchContent,
  getWorkbenchMeta,
  putWorkbenchContent,
  restoreWorkbench,
} from '@/api/client'
import { useToast } from '@/context/Toast'
import { useAutoSave } from '@/hooks/useAutoSave'
import { SaveStateBar } from '@/components/editors/SaveStateBar'
import { MarkdownEditor, type EditorMode } from '@/components/editors/MarkdownEditor'

/** REQ/MAND/TPL/SCORE 登记表所在文件：行序=编号，增删行会整体漂移（assemble 解析协议）。 */
const MACHINE_INPUTS = ['analysis/requirements-business.md', 'analysis/requirements-format.md', 'analysis/evaluation.md']

/** 表格行数（数据行；分隔行 `|---|` 与表头计法一致即可作漂移探测）。 */
function tableRows(text: string): number {
  return text.split('\n').filter((l) => l.startsWith('|') && !/^\|\s*[-:]/.test(l)).length
}

export function WorkbenchViewer({
  taskId,
  path,
  anchorLine = null,
}: {
  taskId: string | null
  path: string | null
  /** 打开时的行号定位（来源追溯）：只读源码视图滚到行；null=常规查看/编辑 */
  anchorLine?: number | null
}) {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [rowWarn, setRowWarn] = useState(false)
  const [mode, setMode] = useState<EditorMode>('split')
  /** 行号定位态：anchor 到达即置位，「返回预览」清除 */
  const [locateLine, setLocateLine] = useState<number | null>(null)

  // 基底哈希与行数基线：保存成功/adopt/恢复三处同步（useAutoSave 的 core 同源）
  const hashRef = useRef('')
  const baseRowsRef = useRef(0)
  const rowsConfirmedRef = useRef(false)
  const rowWarnRef = useRef(false)
  const latest = useRef('')
  latest.current = text

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['workbench', taskId, 'content', path],
    queryFn: async () => await getWorkbenchContent(taskId!, path!),
    enabled: !!taskId && !!path,
  })

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['workbench', taskId] })
  }, [queryClient, taskId])

  const auto = useAutoSave({
    save: async (force) => {
      const res = await putWorkbenchContent(taskId!, path!, latest.current, hashRef.current, force)
      hashRef.current = res.hash
      baseRowsRef.current = tableRows(latest.current)
      invalidate()
      return res.hash
    },
    fetchMeta: async () => (await getWorkbenchMeta(taskId!, path!)).hash,
    initialVersion: '',
    enabled: !!taskId && !!path,
    // 机器输入行数漂移闸：防抖到期时拦截（不发起保存、保持 dirty），弹确认条
    beforeSave: () => {
      if (rowsConfirmedRef.current || !path || !MACHINE_INPUTS.includes(path)) return true
      if (tableRows(latest.current) === baseRowsRef.current) return true
      rowWarnRef.current = true
      setRowWarn(true)
      return false
    },
    onExternalUpdate: () => {
      void adoptLatest() // 查看态静默跟随（模型重跑后刷新）
    },
  })

  /** 拉取最新：换基底（无改动静默跟随 / 冲突时用户已知情选择丢弃本地）。 */
  const adoptLatest = useCallback(async () => {
    if (!taskId || !path) return
    const fresh = await getWorkbenchContent(taskId, path)
    setText(fresh.content)
    hashRef.current = fresh.hash
    baseRowsRef.current = tableRows(fresh.content)
    rowWarnRef.current = false
    rowsConfirmedRef.current = false
    auto.reset(fresh.hash)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, path])

  // 切换文件：整体重置编辑态（只在 path 变化时；data 刷新不打断编辑）
  useEffect(() => {
    setEditing(false)
    setRowWarn(false)
    setLocateLine(null)
    rowWarnRef.current = false
    rowsConfirmedRef.current = false
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  // anchor 行号定位（来源追溯跳原文）：内容就绪后进入只读定位视图
  useEffect(() => {
    if (anchorLine != null && data) setLocateLine(anchorLine)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorLine, path, !!data])

  // 内容同步：无本地改动时跟随服务端（首次加载与外部更新后的静默跟随）
  useEffect(() => {
    if (!data) return
    const s = auto.state
    if (s === 'dirty' || s === 'saving' || s === 'conflict' || s === 'error') return
    setText(data.content)
    hashRef.current = data.hash
    baseRowsRef.current = tableRows(data.content)
    auto.reset(data.hash)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

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

  const display = path.split('/').pop() ?? path
  const editable = data.editable

  const finishEdit = () => {
    if (auto.state === 'conflict') {
      toast('请先裁决：拉取最新或保留我的版本', 'error')
      return
    }
    if (auto.state === 'dirty') void auto.saveNow()
    setEditing(false)
  }

  const handleRestore = async () => {
    if (!taskId || !path) return
    try {
      const res = await restoreWorkbench(taskId, path)
      setText(res.content)
      hashRef.current = res.hash
      baseRowsRef.current = tableRows(res.content)
      rowWarnRef.current = false
      rowsConfirmedRef.current = false
      auto.reset(res.hash)
      setEditing(false)
      invalidate()
      toast('已恢复上一版（可再次恢复撤销）', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <div className="ap-ws">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b pl-4 pr-[88px] py-3">
        <span className="truncate text-sm font-semibold">{display}</span>
        <span className="rounded-full bg-accent px-2 py-0.5 text-xs text-muted-foreground">工作台</span>
        {data.revised && (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">已人工修订</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {editing && <SaveStateBar state={auto.state} lastSavedAt={auto.lastSavedAt} onRetry={() => void auto.saveNow()} />}
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
          {editable && data.has_restore && !editing && (
            <button
              type="button"
              onClick={() => void handleRestore()}
              title="当前内容自动入恢复点栈（保留 3 个），可再次恢复撤销"
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <History className="h-3.5 w-3.5" />
              恢复上一版
            </button>
          )}
          {editing && (
            <button
              type="button"
              onClick={finishEdit}
              className="rounded-md bg-inverse px-2.5 py-1 text-xs text-primary-foreground hover:opacity-90"
            >
              完成编辑
            </button>
          )}
        </div>
      </div>

      {(auto.state === 'conflict' || rowWarn) && (
        <div className="border-b border-warning/50 bg-warning/10 px-4 py-2 text-xs text-warning">
          {auto.state === 'conflict' ? (
            <div className="flex flex-wrap items-center gap-3">
              <span>文件已被其他修改更新（可能是模型重跑），你的本地改动与其冲突。</span>
              <button type="button" className="underline" onClick={() => void adoptLatest()}>
                拉取最新内容
              </button>
              <button type="button" className="underline" onClick={() => void auto.saveNow(true)}>
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
                  void auto.saveNow()
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

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-4">
        {locateLine != null && !editing ? (
          <>
            <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
              <span>
                已定位到第 {locateLine} 行（原文出处锚点）· 文件只读，修改请重新上传解析
              </span>
              <button
                type="button"
                onClick={() => setLocateLine(null)}
                className="ml-auto flex items-center gap-1 rounded-md border border-line px-2 py-0.5 hover:border-primary"
              >
                <Eye className="h-3 w-3" />
                返回预览
              </button>
            </div>
            <MarkdownEditor value={text} mode="source" readOnly anchorLine={locateLine} />
          </>
        ) : editing ? (
          <MarkdownEditor
            value={text}
            onChange={(v) => {
              setText(v)
              auto.markDirty()
            }}
            mode={mode}
            onModeChange={setMode}
          />
        ) : (
          <MarkdownEditor value={text} mode="preview" viewOnly className="prose-sm" />
        )}
      </div>
    </div>
  )
}
