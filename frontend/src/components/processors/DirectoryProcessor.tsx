/**
 * tender.directory 处理程序（P3：查看 + 编辑闭环）。
 *
 * 查看：响应文件分册 → 目录树（来源徽章/交付形态/概述）→ 来源登记表 → lineage 告警。
 * 编辑：同级拖拽排序 + 改名 + 新增/删除节点（标注字段不可改但整节点保留）。
 * 并发策略（文件夹语义，无租约）：发布即覆盖（服务端留恢复点）；编辑器轮询探测
 * 外部更新——无本地改动则静默跟随，有改动则交用户裁决（拉取最新 / 保留我的=强制覆盖）；
 * 保存撞上外部更新同样二选一。永不静默丢用户编辑；关闭时冲刷挂起保存。
 * 运行期 _id 仅用于树寻址，序列化时剥离、不落盘。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  CornerDownRight,
  FileText,
  GripVertical,
  History,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react'
import type { ProcessorProps } from '@/artifacts/registry'
import { getArtifactContent, listArtifacts, restoreArtifact, updateArtifactContent } from '@/api/client'
import { cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'

interface TocNode {
  目录名称: string
  level: number
  children?: TocNode[]
  来源?: string[]
  来源位置?: string[]
  交付形态?: string
  归位理由?: string
  理由来源?: string[]
  节点概述?: string
}

/** 编辑态树节点：_id 为运行期寻址键，保存时剥离；children 递归为 EditNode。 */
interface EditNode extends Omit<TocNode, 'children'> {
  children?: EditNode[]
  _id: string
}

interface RegistryEntry {
  type?: string
  text?: string
  出处?: string
}

interface DirectoryData {
  response_documents?: { name?: string; scope?: string; directory?: EditNode[] }[]
  registry?: Record<string, RegistryEntry>
  meta?: Record<string, string>
  lineage_check?: { unused_ids?: string[]; dangling_ids?: string[] }
  warning?: string
}

type SaveStatus = 'saved' | 'saving' | 'error'

/** 来源位置徽章配色：MAND=红 TPL=蓝 REQ=青 SCORE=琥珀 */
function badgeClass(id: string): string {
  if (id.startsWith('MAND')) return 'bg-red-100 text-red-700'
  if (id.startsWith('TPL')) return 'bg-blue-100 text-blue-700'
  if (id.startsWith('REQ')) return 'bg-teal-100 text-teal-700'
  if (id.startsWith('SCORE')) return 'bg-amber-100 text-amber-700'
  return 'bg-muted text-muted-foreground'
}

function parse(raw: string): DirectoryData | null {
  try {
    const data = JSON.parse(raw) as DirectoryData
    return Array.isArray(data.response_documents) ? data : null
  } catch {
    return null
  }
}

// ---------- 树寻址（编辑操作用） ----------

function findInList(list: EditNode[], id: string): { list: EditNode[]; index: number } | null {
  for (let i = 0; i < list.length; i++) {
    if (list[i]._id === id) return { list, index: i }
    if (list[i].children?.length) {
      const r = findInList(list[i].children!, id)
      if (r) return r
    }
  }
  return null
}

function findInDocs(docs: DirectoryData, id: string): { list: EditNode[]; index: number } | null {
  for (const doc of docs.response_documents ?? []) {
    const r = findInList(doc.directory ?? [], id)
    if (r) return r
  }
  return null
}

/** 节点所属父列表的 key（父节点 _id 或 `doc:<i>`）——判定拖拽是否同父。 */
function parentKeyOf(docs: DirectoryData, id: string): string | null {
  const walk = (list: EditNode[], key: string): string | null => {
    for (const n of list) {
      if (n._id === id) return key
      if (n.children?.length) {
        const r = walk(n.children, n._id)
        if (r) return r
      }
    }
    return null
  }
  const ds = docs.response_documents ?? []
  for (let i = 0; i < ds.length; i++) {
    const r = walk(ds[i].directory ?? [], `doc:${i}`)
    if (r !== null) return r
  }
  return null
}

function assignIds(data: DirectoryData): DirectoryData {
  const walk = (list: EditNode[]) => {
    for (const n of list) {
      n._id = crypto.randomUUID()
      if (n.children?.length) walk(n.children)
    }
  }
  for (const doc of data.response_documents ?? []) walk(doc.directory ?? [])
  return data
}

function stripIds(data: DirectoryData): DirectoryData {
  return JSON.parse(JSON.stringify(data, (_k, v) => (_k === '_id' ? undefined : v)))
}

function newNode(level: number): EditNode {
  return {
    _id: crypto.randomUUID(),
    目录名称: '新章节',
    level,
    children: [],
    来源: [],
    来源位置: [],
    交付形态: '',
    归位理由: '',
    理由来源: [],
    节点概述: '',
  }
}

// ---------- 主组件 ----------

export function DirectoryProcessor({ artifact, content }: ProcessorProps) {
  const data = useMemo(() => parse(content), [content])
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const [editing, setEditing] = useState(false)
  const [docs, setDocs] = useState<DirectoryData | null>(null)
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [renaming, setRenaming] = useState<{ id: string; draft: string } | null>(null)
  const [status, setStatus] = useState<SaveStatus>('saved')
  const [conflict, setConflict] = useState(false)
  const [drag, setDrag] = useState<{ id: string; parentKey: string } | null>(null)
  const [dropHint, setDropHint] = useState<{ id: string; pos: 'above' | 'below' } | null>(null)

  // refs：轮询/防抖/卸载冲刷需要最新值，避免闭包过期
  const docsRef = useRef<DirectoryData | null>(null)
  const seqRef = useRef(artifact.content_seq)
  const dirtyRef = useRef(false)
  const conflictRef = useRef(false)
  const timerRef = useRef<number | null>(null)
  const pollRef = useRef<number | null>(null)
  const savingRef = useRef(false)
  docsRef.current = docs
  conflictRef.current = conflict

  const doSave = useCallback(
    async (force = false): Promise<boolean> => {
      const d = docsRef.current
      if (!d || savingRef.current) return true
      savingRef.current = true
      setStatus('saving')
      try {
        const res = await updateArtifactContent(artifact.artifact_id, stripIds(d), seqRef.current, force)
        seqRef.current = res.content_seq
        dirtyRef.current = false
        setStatus('saved')
        void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
        return true
      } catch (e) {
        setStatus('error')
        const err = e as Error & { status?: number }
        if (err.status === 409) {
          // 探测信号：内容已被外部更新 → 交用户裁决（拉取最新 / 保留我的）
          setConflict(true)
        }
        return false
      } finally {
        savingRef.current = false
      }
    },
    [artifact.artifact_id, queryClient],
  )

  const scheduleSave = useCallback(() => {
    dirtyRef.current = true
    if (timerRef.current) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      void doSave()
    }, 800)
  }, [doSave])

  const mutate = useCallback(
    (fn: (d: DirectoryData) => void) => {
      setDocs((prev) => {
        if (!prev) return prev
        const next = structuredClone(prev)
        fn(next)
        return next
      })
      scheduleSave()
    },
    [scheduleSave],
  )

  const stopEditing = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current)
    timerRef.current = null
    if (pollRef.current) window.clearInterval(pollRef.current)
    pollRef.current = null
    setEditing(false)
    setRenaming(null)
    setDrag(null)
    setDropHint(null)
    setConflict(false)
  }, [])

  /** 以服务端最新内容作为编辑基底（无本地改动时静默跟随外部更新 / 用户选择「拉取最新」） */
  const adoptLatest = useCallback(async () => {
    try {
      const [{ artifacts: rows }, { content: raw }] = await Promise.all([
        listArtifacts(),
        getArtifactContent(artifact.artifact_id),
      ])
      const row = rows.find((a) => a.artifact_id === artifact.artifact_id)
      const fresh = parse(raw)
      if (!fresh || !row) return
      seqRef.current = row.content_seq
      dirtyRef.current = false
      setStatus('saved')
      setDocs(assignIds(structuredClone(fresh)))
    } catch {
      /* 探测失败静默，下次轮询再试 */
    }
  }, [artifact.artifact_id])

  const startEdit = () => {
    if (!data) return
    seqRef.current = artifact.content_seq
    dirtyRef.current = false
    setStatus('saved')
    setConflict(false)
    const clone = assignIds(structuredClone(data))
    // 编辑态默认展开前两层，保证拖拽目标可见
    const ex = new Set<string>()
    const walkAdd = (list: EditNode[], depth: number) => {
      for (const n of list) {
        if (n.children?.length && depth < 2) {
          ex.add(n._id)
          walkAdd(n.children, depth + 1)
        }
      }
    }
    for (const doc of clone.response_documents ?? []) walkAdd(doc.directory ?? [], 0)
    setExpanded(ex)
    setDocs(clone)
    setEditing(true)
    // 外部更新探测（文件夹语义）：文件被 AI 发布/别处保存覆盖时——
    // 无本地改动 → 静默跟随最新；有本地改动 → 弹「拉取最新 / 保留我的」由用户裁决
    pollRef.current = window.setInterval(() => {
      if (savingRef.current || conflictRef.current) return
      listArtifacts()
        .then(({ artifacts: rows }) => {
          const row = rows.find((a) => a.artifact_id === artifact.artifact_id)
          if (!row || row.content_seq <= seqRef.current) return
          if (dirtyRef.current) setConflict(true)
          else void adoptLatest()
        })
        .catch(() => {})
    }, 5_000)
  }

  const exitEdit = async () => {
    // 冲突未裁决：留在编辑态由横幅按钮收尾（此时退出=静默丢用户编辑）
    if (conflictRef.current) {
      toast('内容有冲突待裁决：请先在上方横幅选择「拉取最新」或「保留我的」', 'error')
      return
    }
    // 保存失败（网络错误/409 刚弹裁决横幅）：同样留在编辑态——
    // 网络错误有「保存失败·点击重试」入口，409 走上一分支，编辑不丢
    if (dirtyRef.current && !(await doSave())) return
    stopEditing()
  }

  const handleRestore = async () => {
    try {
      await restoreArtifact(artifact.artifact_id)
      toast('已恢复上一版', 'success')
      await queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  // 卸载（模态关闭即处理器卸载）：冲刷挂起保存；若撞上外部更新，按「主导权归用户」强制保留用户版本
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current)
        if (dirtyRef.current) {
          void (async () => {
            if (!(await doSave())) await doSave(true)
          })()
        }
      }
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---------- 编辑操作 ----------

  const ops = {
    rename: (id: string, name: string) =>
      mutate((d) => {
        const c = findInDocs(d, id)
        if (c) c.list[c.index].目录名称 = name
      }),
    remove: (id: string) =>
      mutate((d) => {
        const c = findInDocs(d, id)
        if (c) c.list.splice(c.index, 1)
      }),
    addSibling: (id: string) =>
      mutate((d) => {
        const c = findInDocs(d, id)
        if (c) c.list.splice(c.index + 1, 0, newNode(c.list[c.index].level))
      }),
    addChild: (id: string) => {
      mutate((d) => {
        const c = findInDocs(d, id)
        if (!c) return
        const n = c.list[c.index]
        n.children = n.children ?? []
        n.children.push(newNode(n.level + 1))
      })
      setExpanded((prev) => new Set(prev).add(id))
    },
    move: (id: string, dir: -1 | 1) =>
      mutate((d) => {
        const c = findInDocs(d, id)
        if (!c) return
        const j = c.index + dir
        if (j >= 0 && j < c.list.length) {
          ;[c.list[c.index], c.list[j]] = [c.list[j], c.list[c.index]]
        }
      }),
    dropOn: (dragId: string, targetId: string, pos: 'above' | 'below') =>
      mutate((d) => {
        const from = findInDocs(d, dragId)
        const to = findInDocs(d, targetId)
        if (!from || !to || from.list !== to.list) return // 仅同级
        const [node] = from.list.splice(from.index, 1)
        let targetIdx = to.index
        if (from.index < to.index) targetIdx -= 1
        from.list.splice(targetIdx + (pos === 'below' ? 1 : 0), 0, node)
      }),
    parentKey: (id: string) => (docs ? parentKeyOf(docs, id) : null),
    toggleExpand: (id: string) =>
      setExpanded((prev) => {
        const n = new Set(prev)
        if (n.has(id)) n.delete(id)
        else n.add(id)
        return n
      }),
  }

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        内容解析失败：不符合投标目录结构
      </div>
    )
  }

  const unused = data.lineage_check?.unused_ids ?? []
  const dangling = data.lineage_check?.dangling_ids ?? []
  const registryEntries = Object.entries(data.registry ?? {})
  const renderDocs = editing ? (docs?.response_documents ?? []) : data.response_documents!

  return (
    <div className="flex flex-col gap-4 text-sm">
      {!editing && (
        <div className="flex items-center gap-2">
          {artifact.editable && (
            <button
              type="button"
              onClick={startEdit}
              className="rounded-md border border-line bg-card px-3 py-1 text-xs font-medium text-foreground hover:border-line-2"
            >
              编辑目录
            </button>
          )}
          {artifact.restore_available && (
            <button
              type="button"
              onClick={() => void handleRestore()}
              className="flex items-center gap-1 rounded-md border border-line bg-card px-3 py-1 text-xs font-medium text-muted-foreground hover:border-line-2 hover:text-foreground"
              title="用上一版内容覆盖当前内容（覆盖前同样留底，可再次撤销）"
            >
              <History className="h-3 w-3" />
              恢复上一版
            </button>
          )}
        </div>
      )}
      {editing && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void exitEdit()}
            className="rounded-md border border-primary bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90"
          >
            完成编辑
          </button>
          {status === 'saving' && <span className="text-xs text-muted-foreground">保存中…</span>}
          {status === 'saved' && <span className="text-xs text-muted-foreground">已保存</span>}
          {status === 'error' && !conflict && (
            <button type="button" onClick={() => void doSave()} className="text-xs text-red-600 hover:underline">
              保存失败 · 点击重试
            </button>
          )}
          <span className="ml-auto text-xs text-muted-foreground">同级拖拽排序 · 悬停节点改名/增删</span>
        </div>
      )}
      {conflict && (
        <Banner
          tone="warn"
          action={
            <span className="flex shrink-0 gap-1">
              <button
                type="button"
                onClick={() => {
                  setConflict(false)
                  void adoptLatest()
                }}
                className="rounded border border-amber-400 px-2 py-0.5 hover:bg-amber-100"
              >
                拉取最新内容
              </button>
              <button
                type="button"
                onClick={() => {
                  void doSave(true).then((ok) => {
                    if (ok) setConflict(false)
                  })
                }}
                className="rounded border border-amber-400 bg-amber-100 px-2 py-0.5 font-medium hover:bg-amber-200"
              >
                保留我的版本
              </button>
            </span>
          }
        >
          内容已被其他会话更新（AI 重新发布或别处保存）。你屏幕上的修改仍然完整——请选择保留哪一份；选「保留我的」会覆盖对方版本（对方版本自动留底）。
        </Banner>
      )}
      {!editing && data.warning && <Banner tone="warn">{data.warning}</Banner>}
      {!editing && (unused.length > 0 || dangling.length > 0) && (
        <Banner tone="warn">
          来源核对：
          {unused.length > 0 && ` ${unused.length} 个来源未被目录引用（${unused.join('、')}）`}
          {dangling.length > 0 && ` ${dangling.length} 个引用悬空（${dangling.join('、')}）`}
        </Banner>
      )}

      {data.meta && Object.keys(data.meta).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(data.meta).map(([k, v]) => (
            <span key={k} className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {k}：{v}
            </span>
          ))}
        </div>
      )}

      {renderDocs.map((doc, idx) => (
        <section key={doc.name ?? idx} className="rounded-lg border">
          <header className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2">
            <FileText className="h-4 w-4 shrink-0 text-primary" />
            <span className="font-semibold">{doc.name ?? '未命名响应文件'}</span>
            <span className="text-xs text-muted-foreground">{(doc.directory ?? []).length} 个顶层章节</span>
          </header>
          {doc.scope && (
            <p className="border-b px-3 py-2 text-xs leading-relaxed text-muted-foreground">{doc.scope}</p>
          )}
          <div className="px-3 py-2">
            {(doc.directory ?? []).map((node, i) =>
              editing ? (
                <EditableNode
                  key={node._id}
                  node={node}
                  depth={0}
                  ops={ops}
                  expanded={expanded}
                  renaming={renaming}
                  setRenaming={setRenaming}
                  drag={drag}
                  setDrag={setDrag}
                  dropHint={dropHint}
                  setDropHint={setDropHint}
                />
              ) : (
                <TreeNode key={i} node={node} depth={0} />
              ),
            )}
          </div>
        </section>
      ))}

      {registryEntries.length > 0 && <RegistrySection entries={registryEntries} />}
    </div>
  )
}

// ---------- 查看态节点 ----------

function TreeNode({ node, depth }: { node: TocNode; depth: number }) {
  // 深层默认折叠，避免长目录一次性铺满；children 键可能缺失（存储内容不物化默认值）
  const [open, setOpen] = useState(depth < 1)
  const children = node.children ?? []
  const hasChildren = children.length > 0
  const tooltip = [node.节点概述, node.归位理由].filter(Boolean).join('｜')

  return (
    <div>
      <div className="flex items-start gap-1.5 py-1" style={{ paddingLeft: depth * 18 }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-1 shrink-0 text-muted-foreground hover:text-foreground"
            aria-label={open ? '折叠' : '展开'}
          >
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="mt-1 w-3.5 shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="leading-5" title={tooltip || undefined}>
              {node.目录名称}
            </span>
            {(node.来源位置 ?? []).map((id) => (
              <span key={id} className={cn('rounded px-1.5 py-px text-[10px] font-medium', badgeClass(id))}>
                {id}
              </span>
            ))}
            {node.交付形态 && (
              <span className="rounded border border-line px-1.5 py-px text-[10px] text-muted-foreground">
                {node.交付形态
              }</span>
            )}
          </div>
          {node.节点概述 && (
            <p className="truncate text-xs leading-5 text-muted-foreground" title={node.节点概述}>
              {node.节点概述}
            </p>
          )}
        </div>
      </div>
      {hasChildren && open && (
        <div>
          {children.map((child, i) => (
            <TreeNode key={i} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------- 编辑态节点 ----------

interface EditableNodeProps {
  node: EditNode
  depth: number
  ops: {
    rename: (id: string, name: string) => void
    remove: (id: string) => void
    addSibling: (id: string) => void
    addChild: (id: string) => void
    move: (id: string, dir: -1 | 1) => void
    dropOn: (dragId: string, targetId: string, pos: 'above' | 'below') => void
    parentKey: (id: string) => string | null
    toggleExpand: (id: string) => void
  }
  expanded: ReadonlySet<string>
  renaming: { id: string; draft: string } | null
  setRenaming: (r: { id: string; draft: string } | null) => void
  drag: { id: string; parentKey: string } | null
  setDrag: (d: { id: string; parentKey: string } | null) => void
  dropHint: { id: string; pos: 'above' | 'below' } | null
  setDropHint: (h: { id: string; pos: 'above' | 'below' } | null) => void
}

function EditableNode(p: EditableNodeProps) {
  const { node, depth, ops } = p
  const [confirmDel, setConfirmDel] = useState(false)
  const children = node.children ?? []
  const hasChildren = children.length > 0
  const open = p.expanded.has(node._id)
  const isRenaming = p.renaming?.id === node._id
  const hint = p.dropHint?.id === node._id ? p.dropHint.pos : null

  const commitRename = () => {
    const draft = p.renaming?.draft.trim()
    if (draft && draft !== node.目录名称) ops.rename(node._id, draft)
    p.setRenaming(null)
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (!p.drag || p.drag.id === node._id) return
    if (ops.parentKey(node._id) !== p.drag.parentKey) return // 仅同级
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const pos = e.clientY < rect.top + rect.height / 2 ? 'above' : 'below'
    if (p.dropHint?.id !== node._id || p.dropHint.pos !== pos) {
      p.setDropHint({ id: node._id, pos })
    }
  }

  return (
    <div>
      <div
        className="group flex items-start gap-1 py-1"
        style={{
          paddingLeft: depth * 18,
          boxShadow:
            hint === 'above'
              ? 'inset 0 2px 0 0 rgb(37 99 235)'
              : hint === 'below'
                ? 'inset 0 -2px 0 0 rgb(37 99 235)'
                : undefined,
        }}
        onDragOver={handleDragOver}
        onDragLeave={() => p.dropHint?.id === node._id && p.setDropHint(null)}
        onDrop={(e) => {
          e.preventDefault()
          if (p.drag && p.dropHint?.id === node._id) ops.dropOn(p.drag.id, node._id, p.dropHint.pos)
          p.setDrag(null)
          p.setDropHint(null)
        }}
      >
        <span
          draggable={!isRenaming}
          onDragStart={(e) => {
            e.dataTransfer.setData('text/plain', node._id)
            e.dataTransfer.effectAllowed = 'move'
            const key = ops.parentKey(node._id)
            if (key) p.setDrag({ id: node._id, parentKey: key })
          }}
          onDragEnd={() => {
            p.setDrag(null)
            p.setDropHint(null)
          }}
          className="mt-1 shrink-0 cursor-grab text-muted-foreground/50 hover:text-muted-foreground active:cursor-grabbing"
          title="拖拽调整顺序（同级）"
        >
          <GripVertical className="h-3.5 w-3.5" />
        </span>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => ops.toggleExpand(node._id)}
            className="mt-1 shrink-0 text-muted-foreground hover:text-foreground"
            aria-label={open ? '折叠' : '展开'}
          >
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="mt-1 w-3.5 shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {isRenaming ? (
              <input
                autoFocus
                value={p.renaming!.draft}
                onChange={(e) => p.setRenaming({ id: node._id, draft: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename()
                  if (e.key === 'Escape') p.setRenaming(null)
                }}
                onBlur={commitRename}
                className="w-56 rounded border border-primary bg-card px-1.5 py-0.5 text-sm outline-none"
              />
            ) : (
              <span className="leading-5">{node.目录名称}</span>
            )}
            {(node.来源位置 ?? []).map((id) => (
              <span key={id} className={cn('rounded px-1.5 py-px text-[10px] font-medium', badgeClass(id))}>
                {id}
              </span>
            ))}
            {node.交付形态 && (
              <span className="rounded border border-line px-1.5 py-px text-[10px] text-muted-foreground">
                {node.交付形态}
              </span>
            )}
            <span className="ml-1 hidden items-center gap-0.5 group-hover:flex">
              <IconBtn title="上移" onClick={() => ops.move(node._id, -1)}>
                <ChevronDown className="h-3 w-3 rotate-180" />
              </IconBtn>
              <IconBtn title="下移" onClick={() => ops.move(node._id, 1)}>
                <ChevronDown className="h-3 w-3" />
              </IconBtn>
              <IconBtn title="改名" onClick={() => p.setRenaming({ id: node._id, draft: node.目录名称 })}>
                <Pencil className="h-3 w-3" />
              </IconBtn>
              <IconBtn title="新增同级" onClick={() => ops.addSibling(node._id)}>
                <Plus className="h-3 w-3" />
              </IconBtn>
              <IconBtn title="新增子级" onClick={() => ops.addChild(node._id)}>
                <CornerDownRight className="h-3 w-3" />
              </IconBtn>
              <IconBtn
                title={confirmDel ? '再点一次确认删除（含子节点）' : '删除'}
                danger={confirmDel}
                onClick={() => {
                  if (confirmDel) ops.remove(node._id)
                  else {
                    setConfirmDel(true)
                    window.setTimeout(() => setConfirmDel(false), 2500)
                  }
                }}
              >
                <Trash2 className="h-3 w-3" />
              </IconBtn>
            </span>
          </div>
          {node.节点概述 && (
            <p className="truncate text-xs leading-5 text-muted-foreground" title={node.节点概述}>
              {node.节点概述}
            </p>
          )}
        </div>
      </div>
      {hasChildren && open && (
        <div>
          {children.map((child) => (
            <EditableNode key={child._id} {...p} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

function IconBtn({
  title,
  onClick,
  danger,
  children,
}: {
  title: string
  onClick: () => void
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={cn(
        'rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground',
        danger && 'text-red-600 hover:bg-red-50 hover:text-red-700',
      )}
    >
      {children}
    </button>
  )
}

// ---------- 通用小组件 ----------

function Banner({
  tone,
  children,
  action,
}: {
  tone: 'warn'
  children: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed',
        tone === 'warn' && 'border-amber-300 bg-amber-50 text-amber-800',
      )}
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span className="flex-1">{children}</span>
      {action}
    </div>
  )
}

function RegistrySection({ entries }: { entries: [string, RegistryEntry][] }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="rounded-lg border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        来源登记表 · {entries.length} 项
      </button>
      {open && (
        <div className="divide-y border-t">
          {entries.map(([id, entry]) => (
            <div key={id} className="flex items-start gap-2 px-3 py-2 text-xs">
              <span className={cn('shrink-0 rounded px-1.5 py-px font-medium', badgeClass(id))}>{id}</span>
              <div className="min-w-0 flex-1">
                <p className="leading-5">{entry.text}</p>
                <p className="text-muted-foreground">{[entry.type, entry.出处].filter(Boolean).join(' · ')}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
