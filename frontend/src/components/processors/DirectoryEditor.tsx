/**
 * 目录编辑器（2026-09-04 批次 4）：编辑态树 + 完整操作集。
 *
 * - 拖拽三落点（原生 HTML5）：目标行上 25%=上方插入 / 下 25%=下方插入 /
 *   中 50%=成为子节点（跨层级移动，整子树 level 重算）；拖入自身后代拦截 + toast；
 * - 右键菜单：升级 / 降级 / 上移 / 下移 / 新增同级 / 新增子级 / 删除（浮层对齐
 *   触发坐标、防溢出视口、Escape/外点关闭）；层级 5 级封顶（超限项禁用+说明）；
 * - undo/redo：本地快照栈 50 步（编辑会话内，组件卸载即清；保存成功不清——
 *   「刚保存完想撤销一步」是合法预期）；Cmd+Z / Shift+Cmd+Z + 头部按钮；
 * - 树操作全部走 directoryTree.ts 纯函数（mutate 包装：快照入栈 + markDirty）。
 * 保存编排（防抖/结构确认条/409 裁决）留在宿主 DirectoryProcessor。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  CornerDownRight,
  GripVertical,
  Pencil,
  Plus,
  Redo2,
  Trash2,
  Undo2,
} from 'lucide-react'
import { useToast } from '@/context/Toast'
import { cn } from '@/lib/utils'
import {
  MAX_LEVEL,
  demote,
  findInDocs,
  findParent,
  isDescendant,
  moveTo,
  promote,
  type DirectoryData,
  type DropPos,
  type EditDoc,
  type EditNode,
} from './directoryTree'
import { numberTree, type NumberedNode, type NumberingValue } from './directoryNumbering'

const HISTORY_LIMIT = 50

interface DirectoryEditorProps {
  docs: DirectoryData
  /** 宿主的 mutate（structuredClone + markDirty 已含）；本组件再包 undo 快照 */
  mutate: (fn: (d: DirectoryData) => void) => void
  /** undo/redo 直换整树（绕过 mutate 的 clone——快照本身即完整副本） */
  setDocs: (d: DirectoryData) => void
  markDirty: () => void
  /** 章节编号格式（宿主编草稿现值）：行内灰色前缀实时预览，节点名仍存裸名 */
  numbering: NumberingValue
}

export function DirectoryEditor({ docs, mutate, setDocs, markDirty, numbering }: DirectoryEditorProps) {
  const { toast } = useToast()
  const docsRef = useRef(docs)
  docsRef.current = docs
  const historyRef = useRef<{ past: DirectoryData[]; future: DirectoryData[] }>({ past: [], future: [] })
  const [histTick, setHistTick] = useState(0) // 栈深度变化驱动按钮可用态

  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => {
    const ex = new Set<string>()
    const walk = (list: EditNode[], depth: number) => {
      for (const n of list) {
        if (n.children?.length && depth < 2) {
          ex.add(n._id ?? '')
          walk(n.children, depth + 1)
        }
      }
    }
    for (const d of docs.response_documents ?? []) walk(d.directory ?? [], 0)
    return ex
  })
  const [renaming, setRenaming] = useState<{ id: string; draft: string } | null>(null)
  const [drag, setDrag] = useState<string | null>(null)
  const [dropHint, setDropHint] = useState<{ id: string; pos: DropPos } | null>(null)
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)

  /** 带 undo 快照的树操作：快照=操作前整树深拷贝（含 _id，树寻址稳定）。 */
  const op = useCallback(
    (fn: (d: DirectoryData) => void) => {
      const h = historyRef.current
      if (docsRef.current) h.past.push(structuredClone(docsRef.current))
      if (h.past.length > HISTORY_LIMIT) h.past.shift()
      h.future = []
      setHistTick((t) => t + 1)
      mutate(fn)
    },
    [mutate],
  )

  const undo = useCallback(() => {
    const h = historyRef.current
    if (!h.past.length) return
    const cur = docsRef.current
    if (cur) h.future.push(structuredClone(cur))
    setDocs(h.past.pop()!)
    markDirty()
    setHistTick((t) => t + 1)
  }, [setDocs, markDirty])

  const redo = useCallback(() => {
    const h = historyRef.current
    if (!h.future.length) return
    const cur = docsRef.current
    if (cur) h.past.push(structuredClone(cur))
    if (h.past.length > HISTORY_LIMIT) h.past.shift()
    setDocs(h.future.pop()!)
    markDirty()
    setHistTick((t) => t + 1)
  }, [setDocs, markDirty])

  // Cmd+Z / Shift+Cmd+Z（改名 input 内的系统 undo 优先——target 为输入控件时跳过）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, redo])

  const docsList: EditDoc[] = docs.response_documents ?? []
  // 编号预览装饰树：与各册 directory 同序同构，切格式/移动节点即重算（纯函数，量小不 memo）
  const numberedDirs = docsList.map((d) => numberTree(d.directory ?? [], numbering))

  const ops = {
    rename: (id: string, name: string) =>
      op((d) => {
        const c = findInDocs((d.response_documents ?? []) as EditDoc[], id)
        if (c) c.list[c.index].目录名称 = name
      }),
    remove: (id: string) =>
      op((d) => {
        const c = findInDocs((d.response_documents ?? []) as EditDoc[], id)
        if (c) c.list.splice(c.index, 1)
      }),
    addSibling: (id: string) =>
      op((d) => {
        const c = findInDocs((d.response_documents ?? []) as EditDoc[], id)
        if (c) c.list.splice(c.index + 1, 0, newNode(c.list[c.index].level))
      }),
    addChild: (id: string) => {
      op((d) => {
        const c = findInDocs((d.response_documents ?? []) as EditDoc[], id)
        if (!c) return
        const n = c.list[c.index]
        n.children = n.children ?? []
        n.children.push(newNode(n.level + 1))
      })
      setExpanded((prev) => new Set(prev).add(id))
    },
    move: (id: string, dir: -1 | 1) =>
      op((d) => {
        const c = findInDocs((d.response_documents ?? []) as EditDoc[], id)
        if (!c) return
        const j = c.index + dir
        if (j >= 0 && j < c.list.length) {
          ;[c.list[c.index], c.list[j]] = [c.list[j], c.list[c.index]]
        }
      }),
    promote: (id: string) => {
      const ok = op2(promote, id)
      if (!ok) toast('根级章节不能再升级', 'error')
    },
    demote: (id: string) => {
      const ok = op2(demote, id)
      if (!ok) {
        const p = findParent(docsList, id)
        const addr = findInDocs(docsList, id)
        if (addr && addr.index === 0) toast('同层第一个节点没有前一个同级可并入', 'error')
        else toast(`层级封顶 ${MAX_LEVEL} 级，不能再降级`, 'error')
        void p
      }
    },
    dropOn: (dragId: string, targetId: string, pos: DropPos) => {
      let ok = false
      op((d) => {
        ok = moveTo((d.response_documents ?? []) as EditDoc[], dragId, targetId, pos)
      })
      if (ok && pos === 'inside') setExpanded((prev) => new Set(prev).add(targetId))
      else if (!ok) toast('不能移动到自身或其子孙节点内', 'error')
    },
    toggleExpand: (id: string) =>
      setExpanded((prev) => {
        const n = new Set(prev)
        if (n.has(id)) n.delete(id)
        else n.add(id)
        return n
      }),
  }

  /** 纯函数操作包装（boolean 结果给 toast 用）。 */
  function op2(
    fn: (docs: EditDoc[], id: string) => boolean,
    id: string,
  ): boolean {
    let ok = false
    op((d) => {
      ok = fn((d.response_documents ?? []) as EditDoc[], id)
    })
    return ok
  }

  return (
    <div className="flex flex-col gap-2" data-hist={histTick}>
      <div className="flex items-center gap-1.5">
        <IconBtn title="撤销（Cmd+Z）" disabled={!historyRef.current.past.length} onClick={undo}>
          <Undo2 className="h-3.5 w-3.5" />
        </IconBtn>
        <IconBtn title="重做（Shift+Cmd+Z）" disabled={!historyRef.current.future.length} onClick={redo}>
          <Redo2 className="h-3.5 w-3.5" />
        </IconBtn>
        <span className="ml-2 text-xs text-muted-foreground">拖拽移动（上/下插入、中间并入） · 右键更多操作</span>
      </div>

      {docsList.map((doc, idx) => (
        <section key={doc.name ?? idx} className="rounded-lg border">
          <header className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2">
            <span className="font-semibold">{doc.name ?? '未命名响应文件'}</span>
            <span className="text-xs text-muted-foreground">{(doc.directory ?? []).length} 个顶层章节</span>
          </header>
          <div className="px-3 py-2" onContextMenu={(e) => e.preventDefault()}>
            {(doc.directory ?? []).map((node, i) => (
              <EditNodeRow
                key={node._id}
                node={node}
                numbered={numberedDirs[idx]?.[i] ?? { node, prefix: '', children: [] }}
                depth={0}
                ops={ops}
                docsList={docsList}
                expanded={expanded}
                renaming={renaming}
                setRenaming={setRenaming}
                drag={drag}
                setDrag={setDrag}
                dropHint={dropHint}
                setDropHint={setDropHint}
                openMenu={(id, x, y) => setMenu({ id, x, y })}
              />
            ))}
          </div>
        </section>
      ))}

      {menu && (
        <TreeContextMenu
          docsList={docsList}
          target={menu.id}
          x={menu.x}
          y={menu.y}
          ops={ops}
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  )
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

// ---------- 编辑态节点（三落点拖拽 + 右键） ----------

interface EditRowProps {
  node: EditNode
  /** 与 node 同位的编号装饰树节点（prefix=编号前缀；children 与 node.children 同序） */
  numbered: NumberedNode
  depth: number
  ops: {
    rename: (id: string, name: string) => void
    remove: (id: string) => void
    addSibling: (id: string) => void
    addChild: (id: string) => void
    move: (id: string, dir: -1 | 1) => void
    promote: (id: string) => void
    demote: (id: string) => void
    dropOn: (dragId: string, targetId: string, pos: DropPos) => void
    toggleExpand: (id: string) => void
  }
  docsList: EditDoc[]
  expanded: ReadonlySet<string>
  renaming: { id: string; draft: string } | null
  setRenaming: (r: { id: string; draft: string } | null) => void
  drag: string | null
  setDrag: (d: string | null) => void
  dropHint: { id: string; pos: DropPos } | null
  setDropHint: (h: { id: string; pos: DropPos } | null) => void
  openMenu: (id: string, x: number, y: number) => void
}

function EditNodeRow(p: EditRowProps) {
  const { node, depth, ops, docsList } = p
  const [confirmDel, setConfirmDel] = useState(false)
  const children = node.children ?? []
  const hasChildren = children.length > 0
  const open = p.expanded.has(node._id ?? '')
  const hint = p.dropHint && p.dropHint.id === node._id ? (p.dropHint.pos as DropPos) : null
  const dragging = p.drag === node._id

  const commitRename = () => {
    const draft = p.renaming?.draft?.trim()
    if (draft && draft !== node.目录名称) ops.rename(node._id!, draft)
    p.setRenaming(null)
  }

  /** 三区落点判定：上 25% / 下 25% / 中 50%（inside=并入子节点）。 */
  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (!p.drag || p.drag === node._id) return
    // 自身后代不可作为落点（不显示提示也不放行）
    if (isDescendant(docsList, p.drag, node._id!)) return
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const rel = (e.clientY - rect.top) / rect.height
    let pos: DropPos = 'inside'
    if (rel < 0.25) pos = 'above'
    else if (rel > 0.75) pos = 'below'
    if (pos === 'inside' && node.level >= MAX_LEVEL) pos = 'below' // 封顶时中区和下区语义合并
    if (p.dropHint?.id !== node._id || p.dropHint!.pos !== pos) {
      p.setDropHint({ id: node._id!, pos })
    }
  }

  return (
    <div>
      <div
        className={cn('group flex items-start gap-1 py-1', dragging && 'opacity-40')}
        style={{
          paddingLeft: depth * 18,
          boxShadow:
            hint === 'above'
              ? 'inset 0 2px 0 0 var(--Color-brand-primary)'
              : hint === 'below'
                ? 'inset 0 -2px 0 0 var(--Color-brand-primary)'
                : hint === 'inside'
                  ? 'inset 0 0 0 2px var(--Color-brand-primary)'
                  : undefined,
          borderRadius: hint === 'inside' ? 4 : undefined,
          background: hint === 'inside' ? 'color-mix(in srgb, var(--Color-brand-primary) 6%, transparent)' : undefined,
        }}
        onDragOver={handleDragOver}
        onDragLeave={() => p.dropHint?.id === node._id && p.setDropHint(null)}
        onDrop={(e) => {
          e.preventDefault()
          if (p.drag && p.dropHint && p.dropHint.id === node._id) ops.dropOn(p.drag, node._id!, p.dropHint.pos)
          p.setDrag(null)
          p.setDropHint(null)
        }}
        onContextMenu={(e) => {
          e.preventDefault()
          p.openMenu(node._id!, e.clientX, e.clientY)
        }}
      >
        <span
          draggable={!p.renaming}
          onDragStart={(e) => {
            e.dataTransfer.setData('text/plain', node._id ?? '')
            e.dataTransfer.effectAllowed = 'move'
            p.setDrag(node._id ?? '')
          }}
          onDragEnd={() => {
            p.setDrag(null)
            p.setDropHint(null)
          }}
          className="mt-1 shrink-0 cursor-grab text-muted-foreground/50 hover:text-muted-foreground active:cursor-grabbing"
          title="拖拽移动：节点上/下边缘=插到同级前后，中间=并入其子节点"
        >
          <GripVertical className="h-3.5 w-3.5" />
        </span>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => ops.toggleExpand(node._id!)}
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
            {p.numbered.prefix && (
              <span className="shrink-0 text-xs leading-5 text-muted-foreground" title="章节编号预览（生成整本时套用）">
                {p.numbered.prefix}
              </span>
            )}
            {p.renaming?.id === node._id ? (
              <input
                autoFocus
                value={p.renaming!.draft}
                onChange={(e) => p.setRenaming({ id: node._id!, draft: e.target.value })}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename()
                  if (e.key === 'Escape') {
                    // 阻断冒泡：取消改名不能连带触发面板 window 级 Escape（收起整个
                    // 编辑器+触发冲刷保存——改名被「提交」而非「取消」）
                    e.stopPropagation()
                    p.setRenaming(null)
                  }
                }}
                onBlur={commitRename}
                className="w-56 rounded border border-primary bg-card px-1.5 py-0.5 text-sm outline-none"
              />
            ) : (
              <span
                className="cursor-text leading-5"
                onDoubleClick={() => p.setRenaming({ id: node._id!, draft: node.目录名称 })}
                title="双击改名（或右键菜单）"
              >
                {node.目录名称}
              </span>
            )}
            <span className="hidden items-center gap-0.5 group-hover:flex">
              <IconBtn title="上移" onClick={() => ops.move(node._id!, -1)}>
                <ChevronDown className="h-3 w-3 rotate-180" />
              </IconBtn>
              <IconBtn title="下移" onClick={() => ops.move(node._id!, 1)}>
                <ChevronDown className="h-3 w-3" />
              </IconBtn>
              <IconBtn title="改名" onClick={() => p.setRenaming({ id: node._id!, draft: node.目录名称 })}>
                <Pencil className="h-3 w-3" />
              </IconBtn>
              <IconBtn title="新增同级" onClick={() => ops.addSibling(node._id!)}>
                <Plus className="h-3 w-3" />
              </IconBtn>
              <IconBtn
                title={node.level >= MAX_LEVEL ? `层级封顶 ${MAX_LEVEL} 级` : '新增子级'}
                disabled={node.level >= MAX_LEVEL}
                onClick={() => ops.addChild(node._id!)}
              >
                <CornerDownRight className="h-3 w-3" />
              </IconBtn>
              <IconBtn
                title={confirmDel ? '再点一次确认删除（含子节点）' : '删除'}
                danger={confirmDel}
                onClick={() => {
                  if (confirmDel) ops.remove(node._id!)
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
          {(children as EditNode[]).map((child, i) => (
            <EditNodeRow
              key={child._id}
              {...p}
              node={child}
              numbered={p.numbered.children[i] ?? { node: child, prefix: '', children: [] }}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------- 右键菜单 ----------

function TreeContextMenu({
  docsList,
  target,
  x,
  y,
  ops,
  onClose,
}: {
  docsList: EditDoc[]
  target: string
  x: number
  y: number
  ops: EditRowProps['ops']
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ left: x, top: y })
  const addr = findInDocs(docsList, target)
  const node = addr?.list[addr?.index ?? 0]
  const isRoot = node ? findParent(docsList, target)?.parent == null : false
  const isFirst = addr ? addr.index === 0 : false

  // 浮层纪律：右缘/底缘越界则回退，绝不溢出视口
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setPos({
      left: Math.min(x, window.innerWidth - r.width - 8),
      top: Math.min(y, window.innerHeight - r.height - 8),
    })
  }, [x, y])

  useEffect(() => {
    const close = () => onClose()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [onClose])

  if (!node) return null
  const items: Array<{ label: string; action?: () => void; disabled?: boolean; danger?: boolean }> = [
    { label: '升级（上移一层）', action: () => ops.promote(target), disabled: isRoot || node.level <= 1 },
    {
      label: `降级（并入上一节点）`,
      action: () => ops.demote(target),
      disabled: isFirst || node.level >= MAX_LEVEL,
    },
    { label: '上移', action: () => ops.move(target, -1), disabled: addr ? addr.index === 0 : true },
    {
      label: '下移',
      action: () => ops.move(target, 1),
      disabled: addr ? addr.index === addr.list.length - 1 : true,
    },
    { label: '新增同级', action: () => ops.addSibling(target) },
    { label: '新增子级', action: () => ops.addChild(target), disabled: node.level >= MAX_LEVEL },
    { label: '删除（含子节点）', action: () => ops.remove(target), danger: true },
  ]

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-44 rounded-lg border border-line bg-card py-1 shadow-lg"
      style={pos}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((it) => (
        <button
          key={it.label}
          type="button"
          disabled={it.disabled}
          title={
            it.disabled && (it.label.includes('降级') || it.label.includes('子级'))
              ? `层级封顶 ${MAX_LEVEL} 级`
              : undefined
          }
          onClick={() => {
            it.action?.()
            onClose()
          }}
          className={cn(
            'flex w-full items-center px-3 py-1.5 text-left text-xs',
            it.disabled
              ? 'cursor-default text-muted-foreground/50'
              : it.danger
                ? 'text-destructive hover:bg-destructive/10'
                : 'text-foreground hover:bg-muted',
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  )
}

function IconBtn({
  title,
  onClick,
  disabled,
  danger,
  children,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={disabled ? `${title}（不可用）` : title}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={cn(
        'rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground',
        danger && 'text-destructive hover:bg-destructive/10',
        disabled && 'cursor-default opacity-40 hover:bg-transparent',
      )}
    >
      {children}
    </button>
  )
}
