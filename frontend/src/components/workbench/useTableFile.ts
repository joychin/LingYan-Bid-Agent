/**
 * 结构化表格文件（写作指引/承诺清单）的编辑状态 hook。
 *
 * 在 WorkbenchViewer 同款保存基建（useQuery content + useAutoSave + base_hash 乐观
 * 并发）之上包一层「rows ↔ md 文本」双向：结构化编辑改 rows → 立即序列化为 md 喂
 * 保存链（文件仍是唯一真值，sidecar 三个消费方现读即生效）；干净态外部更新静默
 * 重解析进表格。编辑中的 rows 是权威（不从序列化产物回读——空单元格已 sanitize
 * 成「—」，回读会把正在输入的空格吞掉）。
 *
 * 解析失败（无表/多表/表头缺列）→ tableMode=false 落源码模式（MarkdownEditor，
 * 与 DocxView 版式失败落文本同款逃生口）；源码模式编辑后切回表格会重解析校验。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getWorkbenchContent,
  getWorkbenchMeta,
  putWorkbenchContent,
  restoreWorkbench,
} from '@/api/client'
import { useToast } from '@/context/Toast'
import { useAutoSave, type UseAutoSaveHandle } from '@/hooks/useAutoSave'
import {
  parseTableFile,
  serializeTableFile,
  type ParsedTableFile,
  type TableSpec,
} from '@/lib/workbenchTable'

export interface TableFileHandle {
  loading: boolean
  loadError: string
  editable: boolean
  revised: boolean
  hasRestore: boolean
  auto: UseAutoSaveHandle<string>
  /** 当前 md 全文（表格模式 = rows 的序列化结果；源码模式 = 编辑中原文） */
  text: string
  rows: string[][]
  /** 表格模式可用（当前文本解析出唯一合法表）；false=源码模式兜底 */
  tableMode: boolean
  /** 切到表格模式（重解析当前文本；失败返回 false 且保持源码模式） */
  enableTableMode: () => boolean
  /** 切到源码模式（MarkdownEditor 直编 md） */
  enableSourceMode: () => void
  editing: boolean
  startEdit: () => void
  finishEdit: () => void
  /** 结构化编辑入口：改行数据（立即序列化 + 置 dirty） */
  applyRows: (rows: string[][]) => void
  /** 源码模式编辑入口 */
  editSource: (v: string) => void
  adoptLatest: () => Promise<void>
  restore: () => Promise<void>
}

export function useTableFile({
  taskId,
  path,
  spec,
}: {
  taskId: string | null
  path: string | null
  spec: TableSpec
}): TableFileHandle {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [rows, setRows] = useState<string[][]>([])
  const [tableMode, setTableMode] = useState(true)
  const [editing, setEditing] = useState(false)

  // 编辑基底（preamble/postamble）只进序列化闭包，不参与渲染——ref 即全部
  const baseRef = useRef<ParsedTableFile | null>(null)
  const hashRef = useRef('')
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
      invalidate()
      return res.hash
    },
    fetchMeta: async () => (await getWorkbenchMeta(taskId!, path!)).hash,
    initialVersion: '',
    enabled: !!taskId && !!path,
    onExternalUpdate: () => void adoptLatest(),
  })

  /** 服务端内容进编辑基底：解析成功进表格模式，失败落源码模式。 */
  const adoptContent = useCallback(
    (content: string, hash: string) => {
      const parsed = parseTableFile(content, spec)
      setText(content)
      baseRef.current = parsed
      setRows(parsed ? parsed.rows : [])
      setTableMode(parsed !== null)
      hashRef.current = hash
      auto.reset(hash)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [spec],
  )

  const adoptLatest = useCallback(async () => {
    if (!taskId || !path) return
    const fresh = await getWorkbenchContent(taskId, path)
    adoptContent(fresh.content, fresh.hash)
  }, [taskId, path, adoptContent])

  // 切换文件：整体重置编辑态（面板按 path 重挂组件，此处兜底同款纪律）
  useEffect(() => {
    setEditing(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  // 内容同步：无本地改动时跟随服务端（首次加载与外部更新后的静默跟随）
  useEffect(() => {
    if (!data) return
    const s = auto.state
    if (s === 'dirty' || s === 'saving' || s === 'conflict' || s === 'error') return
    adoptContent(data.content, data.hash)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const applyRows = useCallback(
    (next: string[][]) => {
      const b = baseRef.current
      if (!b) return
      setRows(next)
      setText(serializeTableFile({ ...b, rows: next }, spec))
      auto.markDirty()
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [spec],
  )

  const editSource = useCallback(
    (v: string) => {
      setText(v)
      auto.markDirty()
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  const enableTableMode = useCallback(() => {
    const parsed = parseTableFile(latest.current, spec)
    if (!parsed) {
      toast('当前内容不是标准表格（找不到唯一合法表），请先修复源码', 'error')
      return false
    }
    baseRef.current = parsed
    setRows(parsed.rows)
    setTableMode(true)
    return true
  }, [spec, toast])

  const enableSourceMode = useCallback(() => setTableMode(false), [])

  const startEdit = useCallback(() => {
    setEditing(true)
    // 结构化基底以进入编辑时的文本为准（外部更新已被 adopt 收敛）
    const parsed = parseTableFile(latest.current, spec)
    if (parsed) {
      baseRef.current = parsed
      setRows(parsed.rows)
    }
  }, [spec])

  const finishEdit = useCallback(() => {
    if (auto.state === 'conflict') {
      toast('请先裁决：拉取最新或保留我的版本', 'error')
      return
    }
    if (auto.state === 'dirty') void auto.saveNow()
    setEditing(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const restore = useCallback(async () => {
    if (!taskId || !path) return
    try {
      const res = await restoreWorkbench(taskId, path)
      adoptContent(res.content, res.hash)
      setEditing(false)
      invalidate()
      toast('已恢复上一版（可再次恢复撤销）', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }, [taskId, path, adoptContent, invalidate, toast])

  return {
    loading: isLoading,
    loadError: isError ? (error instanceof Error ? error.message : String(error)) : '',
    editable: data?.editable ?? false,
    revised: data?.revised ?? false,
    hasRestore: data?.has_restore ?? false,
    auto,
    text,
    rows,
    tableMode,
    enableTableMode,
    enableSourceMode,
    editing,
    startEdit,
    finishEdit,
    applyRows,
    editSource,
    adoptLatest,
    restore,
  }
}
