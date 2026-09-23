import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown,
  Copy,
  FileText,
  Layers,
  ListChecks,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import type { MtBlock, MtFile, MtOutlineNode } from '@/api/client'
import { fetchMtFileBlob, reparseMtFile, uploadMtFile } from '@/api/client'
import { Button } from '@/components/ui/button'
import { ModalShell } from '@/components/ui/ModalShell'
import { DrawerShell } from '@/components/ui/DrawerShell'
import { useDebounced } from '@/hooks/useDebounced'
import { ErrorCard } from '@/components/ErrorCard'
import { Loader } from '@/components/ai/Loader'
import { OriginalView, originalPreviewable, type OriginalSource } from '@/components/preview/OriginalView'
import {
  useCreateMtBlock,
  useDeleteMtBlock,
  useDeleteMtFile,
  useMtBlockContent,
  useMtBlocks,
  useMtFileContent,
  useMtFiles,
  useMtOutline,
  useUpdateMtBlock,
} from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { filterOutline, nodeInBlock, overlappingBlocks } from '@/lib/materialsBlocks'
import { cn, formatRelativeTime } from '@/lib/utils'

/** 区间显示：L12-L40 / L12（多区间顿号连接）。 */
function rangesStr(ranges: number[][] | undefined): string {
  return (ranges ?? [])
    .map(([s, e]) => (e && e !== s ? `L${s}-L${e}` : `L${s}`))
    .join('、')
}

// ===== 目录树纯函数（勾选/折叠共用 key=start_line） =====

function nodeKey(n: MtOutlineNode, depth: number, i: number): string {
  return String(n.start_line ?? `n${depth}-${i}`)
}

function collectParentKeys(nodes: MtOutlineNode[], out: Set<string> = new Set()): Set<string> {
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]
    if (n.children?.length) {
      out.add(nodeKey(n, 0, i))
      collectParentKeys(n.children, out)
    }
  }
  return out
}

function topKeys(nodes: MtOutlineNode[]): Set<string> {
  const out = new Set<string>()
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].children?.length) out.add(nodeKey(nodes[i], 0, i))
  }
  return out
}

function subtreeKeys(node: MtOutlineNode): string[] {
  const keys: string[] = []
  const walk = (n: MtOutlineNode) => {
    if (n.start_line != null) keys.push(String(n.start_line))
    for (const c of n.children ?? []) walk(c)
  }
  walk(node)
  return keys
}

function findNodeByKey(
  nodes: MtOutlineNode[],
  key: string,
  depth = 0,
): MtOutlineNode | null {
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]
    if (nodeKey(n, depth, i) === key) return n
    if (n.children?.length) {
      const hit = findNodeByKey(n.children, key, depth + 1)
      if (hit) return hit
    }
  }
  return null
}

/** 节点勾选三态：all=子树全选 / some=部分（半选框）/ none。 */
function nodeCheckState(node: MtOutlineNode, checked: Set<string>): 'all' | 'some' | 'none' {
  const keys = subtreeKeys(node)
  const picked = keys.filter((k) => checked.has(k)).length
  if (picked === 0) return 'none'
  return picked === keys.length ? 'all' : 'some'
}

// ===== 挑章节：目录树（点节点=右侧预览；勾选=建块区间） =====

function OutlineTree({
  nodes,
  checked,
  onToggle,
  expanded,
  onToggleExpand,
  onPreview,
  previewKey,
  filtering,
  fileBlocks,
  depth = 0,
}: {
  nodes: MtOutlineNode[]
  checked: Set<string>
  onToggle: (node: MtOutlineNode) => void
  expanded: ReadonlySet<string>
  onToggleExpand: (key: string) => void
  onPreview: (key: string) => void
  previewKey: string | null
  filtering: boolean
  fileBlocks: MtBlock[]
  depth?: number
}) {
  return (
    <div className="mtw-tree">
      {nodes.map((n, i) => {
        const key = nodeKey(n, depth, i)
        const state = nodeCheckState(n, checked)
        const on = state !== 'none'
        const hasChildren = Boolean(n.children?.length)
        const open = filtering || expanded.has(key)
        const canPreview = n.start_line != null && n.end_line != null
        return (
          <div key={key}>
            <div
              className={cn(
                'mt-node',
                on && 'mt-node--checked',
                canPreview && previewKey === key && 'mt-node--previewing',
              )}
              style={{ paddingLeft: 8 + depth * 18 }}
              onClick={() => canPreview && onPreview(key)}
              role={canPreview ? 'button' : undefined}
            >
              {hasChildren ? (
                <button
                  type="button"
                  className="mt-node-chev"
                  aria-label={open ? '收起子章节' : '展开子章节'}
                  onClick={(e) => {
                    e.stopPropagation()
                    onToggleExpand(key)
                  }}
                >
                  <ChevronDown className={cn('mt-chev-ico', open && 'mt-chev-ico--open')} />
                </button>
              ) : (
                <span className="mt-node-chev mt-node-chev--leaf" />
              )}
              <input
                type="checkbox"
                checked={on}
                ref={(el) => {
                  if (el) el.indeterminate = state === 'some'
                }}
                onClick={(e) => e.stopPropagation()}
                onChange={() => onToggle(n)}
              />
              <span className="mt-node-title">{n['标题'] || '（无标题）'}</span>
              {nodeInBlock(n, fileBlocks) && <span className="mt-node-badge">已建块</span>}
              <span className="mt-node-range">
                {n.chars != null && `约${n.chars.toLocaleString()}字 · `}
                {n.start_line && n.end_line ? `L${n.start_line}-L${n.end_line}` : ''}
              </span>
            </div>
            {hasChildren && open ? (
              <OutlineTree
                nodes={n.children ?? []}
                checked={checked}
                onToggle={onToggle}
                expanded={expanded}
                onToggleExpand={onToggleExpand}
                onPreview={onPreview}
                previewKey={previewKey}
                filtering={filtering}
                fileBlocks={fileBlocks}
                depth={depth + 1}
              />
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

// ===== 行号槽正文预览（块详情与挑章节预览共用） =====

function LinePreview({ sections, loading, error, maxLines }: {
  sections: { start: number; end: number; text: string }[] | undefined
  loading: boolean
  error: boolean
  maxLines?: number
}) {
  if (loading) {
    return (
      <div className="mtw-preview-state">
        <Loader variant="classic" size="sm" tone="muted" /> 加载内容…
      </div>
    )
  }
  if (error) {
    return <div className="mtw-preview-state">内容加载失败——稍后重试</div>
  }
  const secs = sections ?? []
  if (secs.length === 0) {
    return <div className="mtw-preview-state">（区间内没有可展示的文本）</div>
  }
  return (
    <div className="mtw-preview">
      {secs.map((sec) =>
        sec.text.split('\n').map((ln, i) => (
          <div key={`${sec.start}-${i}`} className="mtw-line">
            <span className="mtw-ln">{sec.start + i}</span>
            <span className="mtw-lt">{ln}</span>
          </div>
        )),
      )}
      {maxLines != null && <div className="mtw-preview-clamp">（章节过长，仅预览前 {maxLines.toLocaleString()} 行）</div>}
    </div>
  )
}

// ===== 文本 / 原件预览切换（分段控件样式与知识库同款） =====

type PreviewMode = 'text' | 'original'

function PreviewSeg({ mode, onChange }: {
  mode: PreviewMode
  onChange: (m: PreviewMode) => void
}) {
  return (
    <div className="kb-seg" role="group" aria-label="预览方式">
      <button
        type="button"
        className={mode === 'text' ? 'kb-seg-btn kb-seg-btn--active' : 'kb-seg-btn'}
        onClick={() => onChange('text')}
      >
        文本
      </button>
      <button
        type="button"
        className={mode === 'original' ? 'kb-seg-btn kb-seg-btn--active' : 'kb-seg-btn'}
        onClick={() => onChange('original')}
      >
        原件
      </button>
    </div>
  )
}

/** 文件扩展名（含点、小写；无扩展名返回空串）。 */
function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

// ===== 主视图 =====

type SortKey = 'range' | 'chars' | 'used'

export function MaterialsLibraryView({ onGoKnowledge }: { onGoKnowledge?: () => void }) {
  const [scope, setScope] = useState<'all' | string>('all')
  const [blockId, setBlockId] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerFileId, setPickerFileId] = useState<string | null>(null)
  const [fileQ, setFileQ] = useState('')
  const [treeQ, setTreeQ] = useState('')
  const [blockQ, setBlockQ] = useState('')
  const [sort, setSort] = useState<SortKey>('range')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [previewKey, setPreviewKey] = useState<string | null>(null)
  const [pvMode, setPvMode] = useState<PreviewMode>('text')
  const expandedInit = useRef<string | null>(null)
  const [title, setTitle] = useState('')
  const [note, setNote] = useState('')
  const [creating, setCreating] = useState(false)
  const [confirmDelFile, setConfirmDelFile] = useState<string | null>(null)
  const [confirmDelBlock, setConfirmDelBlock] = useState(false)
  const [reparsing, setReparsing] = useState<string | null>(null)
  const [uploading, setUploading] = useState<{ name: string; percent: number } | null>(null)
  // 备注编辑（详情区就地）
  const [editTitle, setEditTitle] = useState('')
  const [editNote, setEditNote] = useState('')
  const [editing, setEditing] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const { toast } = useToast()

  const debouncedQ = useDebounced(blockQ, 300).trim()
  const {
    data: filesData,
    isPending: filesLoading,
    isError: filesError,
    refetch: refetchFiles,
  } = useMtFiles()
  const { data: allBlocksData } = useMtBlocks()
  const { data: searchBlocksData, isFetching: searching } = useMtBlocks(debouncedQ || undefined)
  const { data: outlineData } = useMtOutline(pickerOpen ? pickerFileId : null)
  const { data: blockContent, isPending: contentLoading, isError: contentError } = useMtBlockContent(
    blockId,
    Boolean(blockId),
  )

  const files = filesData?.files ?? []
  const allBlocks = allBlocksData?.blocks ?? []
  const fileId2Name = useMemo(() => new Map(files.map((f) => [f.id, f.file_name])), [files])
  const activeFile = scope === 'all' ? null : files.find((f) => f.id === scope) ?? null
  const pickerFile = pickerFileId ? files.find((f) => f.id === pickerFileId) ?? null : null

  // 中栏块清单：q 非空走服务端 FTS（含正文），再按左栏范围过滤
  const blockSource = debouncedQ ? searchBlocksData?.blocks ?? [] : allBlocks
  const visibleBlocks = useMemo(() => {
    let bs = blockSource
    if (scope !== 'all') bs = bs.filter((b) => b.file_id === scope)
    const sorted = [...bs]
    if (sort === 'chars') sorted.sort((a, b) => (b.chars ?? 0) - (a.chars ?? 0))
    else if (sort === 'used') sorted.sort((a, b) => (b.use_count ?? 0) - (a.use_count ?? 0))
    else
      sorted.sort(
        (a, b) =>
          (a.ranges?.[0]?.[0] ?? 0) - (b.ranges?.[0]?.[0] ?? 0) ||
          a.file_id.localeCompare(b.file_id),
      )
    return sorted
  }, [blockSource, scope, sort])

  // 选中块失效（删除/换范围）→ 落到首个可见块
  useEffect(() => {
    if (blockId && visibleBlocks.some((b) => b.id === blockId)) return
    setBlockId(visibleBlocks[0]?.id ?? null)
  }, [blockId, visibleBlocks])

  const block = allBlocks.find((b) => b.id === blockId) ?? null
  // 「原件」预览源：挑章节=当前文件 / 块详情=块所属文件——都是整份文件的版式（非仅区间）
  const originalSource = useMemo<OriginalSource | null>(() => {
    const fid = pickerOpen ? pickerFileId : block?.file_id
    const fname = pickerOpen ? pickerFile?.file_name : fileId2Name.get(block?.file_id ?? '')
    if (!fid || !fname) return null
    const ext = extOf(fname)
    if (!originalPreviewable(ext)) return null
    return {
      id: fid,
      ext,
      fetchBlob: fetchMtFileBlob,
      queryKey: ['mt', 'raw', fid],
      failHint: '版式渲染失败——完整原件请在数据目录的 materials/files/ 下打开',
    }
  }, [pickerOpen, pickerFileId, pickerFile, block, fileId2Name])
  // 中栏「新建素材」可用性：选定文件且解析完成（挑章节覆盖层开着时置灰防误重置勾选）
  const canNewBlock =
    scope !== 'all' && !pickerOpen && activeFile?.parse_status === 'ready'

  // ===== 挑章节 =====
  const outline = useMemo(() => outlineData?.outline ?? [], [outlineData])
  const pickerBlocks = useMemo(
    () => allBlocks.filter((b) => b.file_id === pickerFileId),
    [allBlocks, pickerFileId],
  )
  // 树过滤（保祖先链；过滤态强制全展开）——独立于文件列表搜索（fileQ）
  const filtered = useMemo(
    () => (treeQ.trim() ? filterOutline(outline, treeQ) : { nodes: outline, hits: 0 }),
    [outline, treeQ],
  )

  // outline 到达后初始化折叠态与预览节点（每个文件只做一次，后续归用户）
  useEffect(() => {
    if (!pickerOpen || !pickerFileId || outline.length === 0) return
    if (expandedInit.current === pickerFileId) return
    expandedInit.current = pickerFileId
    setExpanded(topKeys(outline))
    const first = outline[0]
    if (first.start_line != null && first.end_line != null) setPreviewKey(nodeKey(first, 0, 0))
  }, [pickerOpen, pickerFileId, outline])

  const toggleNode = (n: MtOutlineNode) => {
    // 级联勾选：勾父级=子树全部加入；取消=子树全部移除（子级可单独再摘出）
    const keys = subtreeKeys(n)
    setChecked((prev) => {
      const next = new Set(prev)
      const allOn = keys.every((k) => next.has(k))
      for (const k of keys) {
        if (allOn) next.delete(k)
        else next.add(k)
      }
      return next
    })
  }

  const toggleExpand = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const checkedRanges = useMemo<[number, number][]>(() => {
    const out: [number, number][] = []
    const walk = (list: MtOutlineNode[]) => {
      for (const n of list) {
        const state = nodeCheckState(n, checked)
        if (state === 'none') continue
        if (state === 'all' && n.start_line != null && n.end_line != null) {
          out.push([n.start_line, n.end_line])
          continue
        }
        // 部分选中：下钻取选中的子区间（如整章里摘掉一节 → 多区间拼接）
        if (n.children?.length) walk(n.children)
        else if (n.start_line != null && n.end_line != null) out.push([n.start_line, n.end_line])
      }
    }
    walk(outline)
    return out.toSorted((a, b) => a[0] - b[0])
  }, [checked, outline])

  // 预览节点（挑章节右半）；跨度上限与服务端一致，超出只拉前 2000 行
  const previewNode = previewKey ? findNodeByKey(outline, previewKey) : null
  const pvStart = previewNode?.start_line ?? 0
  const pvRawEnd = previewNode?.end_line ?? 0
  const pvClamped = pvRawEnd - pvStart + 1 > 2000
  const pvEnd = pvClamped ? pvStart + 1999 : pvRawEnd
  const {
    data: pvContent,
    isPending: pvLoading,
    isError: pvError,
  } = useMtFileContent(pickerOpen ? pickerFileId : null, pvStart, pvEnd)

  // 建块前的重复探测（提示不阻断——裁决归用户）
  const dup = useMemo(() => overlappingBlocks(checkedRanges, pickerBlocks), [checkedRanges, pickerBlocks])

  // ===== 数据操作 =====
  const createBlock = useCreateMtBlock()
  const updateBlock = useUpdateMtBlock()
  const delBlock = useDeleteMtBlock()
  const delFile = useDeleteMtFile()

  const onUpload = async (file: File) => {
    setUploading({ name: file.name, percent: 0 })
    try {
      await uploadMtFile(file, (p) => setUploading((u) => (u ? { ...u, percent: p } : null)))
      await qc.invalidateQueries({ queryKey: ['mt', 'files'] })
      toast('已上传，正在解析目录…', 'info')
    } catch (e) {
      toast(e instanceof Error ? e.message : '上传失败', 'error')
    } finally {
      setUploading(null)
    }
  }

  const onDeleteFile = (f: MtFile) => {
    if (confirmDelFile !== f.id) {
      setConfirmDelFile(f.id)
      window.setTimeout(() => setConfirmDelFile((cur) => (cur === f.id ? null : cur)), 3000)
      return
    }
    setConfirmDelFile(null)
    delFile.mutate(f.id, {
      onSuccess: () => {
        if (scope === f.id) setScope('all')
        if (pickerFileId === f.id) {
          setPickerOpen(false)
          setPickerFileId(null)
        }
      },
    })
  }

  const onReparseFile = async (f: MtFile) => {
    setReparsing(f.id)
    try {
      await reparseMtFile(f.id)
      await qc.invalidateQueries({ queryKey: ['mt', 'files'] })
      toast('已重新开始解析…', 'info')
    } catch (e) {
      // 409=正在解析中/404=已被删：刷新列表即对齐真实状态
      toast(e instanceof Error ? e.message : '重试失败', 'error')
      void qc.invalidateQueries({ queryKey: ['mt', 'files'] })
    } finally {
      setReparsing(null)
    }
  }

  const enterPicker = (f: MtFile) => {
    // 换文件才重置勾选/草稿；误关覆盖层后重开同文件保留现场
    const switching = pickerFileId !== f.id
    setScope(f.id)
    setPickerFileId(f.id)
    if (switching) {
      setChecked(new Set())
      setExpanded(new Set())
      setPreviewKey(null)
      expandedInit.current = null
      setTitle('')
      setNote('')
      setTreeQ('')
    }
    setPickerOpen(true)
  }

  const submitBlock = async () => {
    if (!pickerFileId || !checkedRanges.length) return
    const fallbackTitle =
      findNodeByKey(outline, String(checkedRanges[0][0]))?.['标题'] ?? '未命名素材块'
    try {
      const created = await createBlock.mutateAsync({
        fileId: pickerFileId,
        body: { title: title.trim() || fallbackTitle, note: note.trim(), ranges: checkedRanges },
      })
      // 等列表回流再选中新块——若先 setBlockId，「选中块失效」effect 会在旧列表上
      // 找不到新块，误判失效拉回首块（既有竞态，创建后详情显示旧块）
      await qc.invalidateQueries({ queryKey: ['mt'] })
      toast('素材块已创建', 'success')
      setCreating(false)
      setChecked(new Set())
      setTitle('')
      setNote('')
      setTreeQ('')
      setScope(pickerFileId)
      setBlockId(created.id)
      setPickerOpen(false)
      setPickerFileId(null)
    } catch (e) {
      toast(e instanceof Error ? e.message : '创建失败', 'error')
    }
  }

  const startEdit = () => {
    if (!block) return
    setEditTitle(block.title)
    setEditNote(block.note ?? '')
    setEditing(true)
  }

  const saveEdit = async () => {
    if (!block) return
    try {
      await updateBlock.mutateAsync({
        id: block.id,
        body: { title: editTitle.trim() || block.title, note: editNote },
      })
      setEditing(false)
    } catch (e) {
      toast(e instanceof Error ? e.message : '保存失败', 'error')
    }
  }

  const onDeleteBlock = () => {
    if (!block) return
    if (!confirmDelBlock) {
      setConfirmDelBlock(true)
      window.setTimeout(() => setConfirmDelBlock(false), 3000)
      return
    }
    setConfirmDelBlock(false)
    delBlock.mutate(block.id, {
      onSuccess: () => {
        setBlockId(null)
        toast('素材块已删除', 'info')
      },
    })
  }

  const copyBlock = async () => {
    const text = (blockContent?.sections ?? []).map((s) => s.text).join('\n\n')
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      toast('已复制正文', 'success')
    } catch {
      toast('复制失败', 'error')
    }
  }

  // ===== 渲染 =====

  const shownFiles = useMemo(() => {
    const q = fileQ.trim().toLowerCase()
    if (!q) return files
    return files.filter((f) => f.file_name.toLowerCase().includes(q))
  }, [files, fileQ])

  const renderFileList = (
    <>
      {!fileQ.trim() && (
        <button
          type="button"
          className={cn('mtw-file-item', 'mtw-file-item--all', scope === 'all' && 'mtw-file-item--active')}
          onClick={() => setScope('all')}
        >
          <Layers className="mtw-file-ico" />
          <span className="mtw-file-body">
            <span className="mtw-file-name">全部素材</span>
            <span className="mtw-file-meta">
              {allBlocks.length} 个素材块 · 跨 {new Set(allBlocks.map((b) => b.file_id)).size} 份文件
            </span>
          </span>
        </button>
      )}
      {uploading && !files.some((f) => f.file_name === uploading.name) && (
        <div className="mtw-file-item mtw-file-item--static">
          <Loader variant="classic" size="sm" tone="muted" />
          <span className="mtw-file-body">
            <span className="mtw-file-name">{uploading.name}</span>
            <span className="mtw-file-meta">上传中 {uploading.percent}%</span>
          </span>
        </div>
      )}
      {shownFiles.map((f) => {
        const ready = f.parse_status === 'ready'
        const warn = ready && Boolean(f.error)
        const parsing = f.parse_status === 'parsing' || f.parse_status === 'pending'
        return (
          <div
            key={f.id}
            className={cn('mtw-file-item', scope === f.id && 'mtw-file-item--active')}
            onClick={() => setScope(f.id)}
            role="button"
          >
            <FileText className="mtw-file-ico" />
            <span className="mtw-file-body">
              <span className="mtw-file-name" title={f.file_name}>{f.file_name}</span>
              <span className="mtw-file-meta" title={warn ? f.error || undefined : undefined}>
                {ready
                  ? `${f.block_count ?? 0} 个素材块${warn ? ' · 勾选区间需复核' : ''}`
                  : f.parse_status === 'failed'
                    ? f.error || '解析失败'
                    : '解析中…'}
              </span>
            </span>
            <span className="mtw-file-ops">
              {ready && (
                <button
                  type="button"
                  className="mtw-icon-btn"
                  aria-label={`挑章节 ${f.file_name}`}
                  title="挑章节建块"
                  onClick={(e) => {
                    e.stopPropagation()
                    enterPicker(f)
                  }}
                >
                  <ListChecks />
                </button>
              )}
              {f.parse_status === 'failed' && (
                <button
                  type="button"
                  className="mtw-icon-btn"
                  aria-label={`重新解析 ${f.file_name}`}
                  title="重试解析"
                  disabled={reparsing === f.id}
                  onClick={(e) => {
                    e.stopPropagation()
                    void onReparseFile(f)
                  }}
                >
                  <RotateCcw />
                </button>
              )}
              {!uploading && !parsing && (
                <button
                  type="button"
                  className={cn('mtw-icon-btn', ready && 'mtw-icon-btn--danger')}
                  aria-label={confirmDelFile === f.id
                    ? `确认删除 ${f.file_name}（将连带删除其 ${f.block_count ?? 0} 个素材块）`
                    : `删除 ${f.file_name}（将连带删除其全部素材块）`}
                  title={confirmDelFile === f.id ? '再点一次确认删除' : '删除文件（连带删除其全部素材块）'}
                  disabled={delFile.isPending}
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteFile(f)
                  }}
                >
                  <Trash2 />
                </button>
              )}
            </span>
            <span
              className={cn(
                'mtw-dot',
                ready && !warn && 'mtw-dot--ok',
                warn && 'mtw-dot--warn',
                f.parse_status === 'failed' && 'mtw-dot--err',
                parsing && 'mtw-dot--run',
              )}
              title={ready
                ? warn
                  ? f.error || undefined
                  : '已解析'
                : f.parse_status === 'failed'
                  ? f.error || '解析失败'
                  : '解析中'}
            />
          </div>
        )
      })}
      {filesLoading && shownFiles.length === 0 && !uploading && (
        <div className="kb-empty">
          <span className="inline-flex items-center gap-1.5">
            <Loader variant="classic" size="sm" tone="muted" />
            加载中…
          </span>
        </div>
      )}
      {filesError && shownFiles.length === 0 && !uploading && (
        // 失败 ≠ 空态（此前连 loading 分支都没有，加载中也闪「还没有文件」）
        <div className="kb-empty">
          <ErrorCard
            message="素材文件列表加载失败，已上传的文件不会丢。"
            code={null}
            retryText="重试"
            onRetry={() => void refetchFiles()}
          />
        </div>
      )}
      {shownFiles.length === 0 && !uploading && !filesLoading && !filesError && (
        <div className="kb-empty">
          {fileQ.trim()
            ? '没有匹配的文件——换个关键词'
            : '还没有文件——点下方「上传文件」传历史标书/范文（仅 .docx），再勾选章节建素材块'}
          {!fileQ.trim() && files.length === 0 && (
            <p className="mtw-lib-alt">
              证明公司真做过什么（合同/验收/证书）？
              {onGoKnowledge ? (
                <button type="button" className="mtw-lib-link" onClick={onGoKnowledge}>
                  去知识库上传
                </button>
              ) : (
                <span>请传「知识库」</span>
              )}
            </p>
          )}
        </div>
      )}
    </>
  )

  const renderBlockList = (
    <>
      {visibleBlocks.map((b) => {
        const src = fileId2Name.get(b.file_id) ?? ''
        return (
          <button
            key={b.id}
            type="button"
            className={cn('mtw-block-item', blockId === b.id && 'mtw-block-item--active')}
            onClick={() => setBlockId(b.id)}
          >
            <span className="mtw-b-title" title={b.title}>{b.title}</span>
            <span className="mtw-b-meta">
              {scope === 'all' ? (
                <span className="mtw-b-src" title={src}>来自 {src}</span>
              ) : (
                <span className="mtw-b-src">{rangesStr(b.ranges)}</span>
              )}
              <span>·</span>
              <span>约 {(b.chars ?? 0).toLocaleString()} 字</span>
              {(b.use_count ?? 0) > 0 ? (
                <span className="mt-usage-badge" title="AI 检索命中与正文注入各计一次">引用 {b.use_count}</span>
              ) : (
                <span className="mtw-b-unused">未引用</span>
              )}
            </span>
          </button>
        )
      })}
      {visibleBlocks.length === 0 && (
        <div className="kb-empty">
          {debouncedQ
            ? searching
              ? '搜索中…'
              : '没有匹配的素材——换个关键词（标题/备注/正文都搜）'
            : scope === 'all'
              ? '还没有素材块——上传历史标书/范文，在目录树上勾选值得复用的章节'
              : '该文件还没有素材块——点上方「新建素材」勾选章节生成'}
        </div>
      )}
    </>
  )

  // ---- 详情区：块详情 ----
  const renderDetailBlock = () => {
    if (!block) {
      return (
        <div className="mtw-detail-empty">
          <Layers />
          <div>在素材列表中选择一个素材块查看内容</div>
        </div>
      )
    }
    const showOriginal = pvMode === 'original' && originalSource != null
    return (
      <>
        <div className="mtw-detail-head" data-tauri-drag-region>
          <div className="mtw-detail-titlerow">
            <div className="mtw-detail-title" title={block.title}>{block.title}</div>
            <div className="mtw-detail-actions">
              <Button size="sm" variant="outline" title="复制正文" onClick={() => void copyBlock()}>
                <Copy className="h-3.5 w-3.5" />
                复制
              </Button>
              <Button
                size="sm"
                variant="outline"
                className={!confirmDelBlock ? 'text-error' : ''}
                title={confirmDelBlock ? '再点一次确认删除' : '删除素材块'}
                aria-label={confirmDelBlock ? `确认删除 ${block.title}` : `删除 ${block.title}`}
                disabled={delBlock.isPending}
                onClick={onDeleteBlock}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {confirmDelBlock ? '确认删除？' : '删除'}
              </Button>
            </div>
          </div>
          <div className="mtw-detail-meta">
            <span>
              来源 <b title={fileId2Name.get(block.file_id) ?? ''}>{fileId2Name.get(block.file_id) ?? ''}</b>
            </span>
            <span>区间 <b className="mtw-mono">{rangesStr(block.ranges)}</b></span>
            <span>约 {(blockContent?.chars ?? block.chars ?? 0).toLocaleString()} 字</span>
            {(block.use_count ?? 0) > 0 ? (
              <span className="mt-usage-badge" title="AI 检索命中与正文注入各计一次">
                AI 引用 {block.use_count} 次{block.last_used_at ? ` · ${formatRelativeTime(block.last_used_at)}` : ''}
              </span>
            ) : (
              <span className="mtw-b-unused">未被 AI 引用过</span>
            )}
          </div>
        </div>
        <div className="mtw-detail-body">
          <div className="mtw-note-card">
            {!editing ? (
              <>
                <div className="mtw-note-labelrow">
                  <span className="mtw-note-label">
                    备注
                    {!block.note && (
                      <span className="mtw-note-missing">——还没写，AI 挑素材时缺少依据</span>
                    )}
                  </span>
                  <button type="button" className="mtw-icon-btn" title="编辑标题/备注" onClick={startEdit}>
                    <Pencil />
                  </button>
                </div>
                {block.note && <div className="mtw-note-text">{block.note}</div>}
              </>
            ) : (
              <div className="mt-note-edit">
                <input
                  className="mt-input"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  placeholder="素材块标题"
                  aria-label="素材块标题"
                />
                <textarea
                  value={editNote}
                  onChange={(e) => setEditNote(e.target.value)}
                  rows={3}
                  placeholder="备注（进检索——写适用场景/亮点，帮助 AI 挑对素材）"
                  aria-label="备注"
                />
                <div className="mt-note-actions">
                  <Button size="sm" onClick={() => void saveEdit()} disabled={updateBlock.isPending}>
                    保存
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                    取消
                  </Button>
                </div>
              </div>
            )}
          </div>
          {originalSource && (
            <div className="mtw-section-label">
              <PreviewSeg mode={pvMode} onChange={setPvMode} />
            </div>
          )}
          <div className="mtw-preview-scroll">
            {showOriginal && originalSource ? (
              <OriginalView key={originalSource.id} source={originalSource} />
            ) : (
              <LinePreview
                sections={blockContent?.sections}
                loading={contentLoading}
                error={contentError}
              />
            )}
          </div>
        </div>
      </>
    )
  }

  // ---- 详情区：挑章节 ----
  const renderPicker = () => {
    const outlineEmpty = outline.length === 0
    return (
      <div className="mtw-picker">
        <div className="mtw-picker-head">
          <button type="button" className="mtw-icon-btn" aria-label="关闭挑章节" title="关闭" onClick={() => setPickerOpen(false)}>
            <X />
          </button>
          <span className="mtw-picker-name" title={pickerFile?.file_name ?? ''}>
            挑章节 · {pickerFile?.file_name ?? ''}
          </span>
          <span className="mtw-picker-meta">{pickerFile?.block_count ?? 0} 个已有素材块</span>
          {!treeQ.trim() && outline.length > 0 && (
            <span className="mtw-treeops">
              <button type="button" className="mtw-text-btn" onClick={() => setExpanded(collectParentKeys(outline))}>
                全部展开
              </button>
              <button type="button" className="mtw-text-btn" onClick={() => setExpanded(new Set())}>
                全部收起
              </button>
            </span>
          )}
          <span className="mtw-picker-hint">点章节=右侧预览 · 勾选=纳入素材块</span>
        </div>
        {outlineEmpty ? (
          <div className="kb-empty">
            {outlineData?.parse_status === 'parsing' || outlineData?.parse_status === 'pending' ? (
              <>
                <Loader variant="classic" size="sm" tone="muted" /> 正在解析目录…
              </>
            ) : treeQ.trim() ? (
              '没有匹配的章节标题——换个关键词'
            ) : (
              (outlineData?.error ?? '该文件没有识别到目录结构，无法挑章节')
            )}
          </div>
        ) : (
          <>
            <div className="mtw-picker-main">
              <div className="mtw-picker-tree">
                <div className="mtw-search mtw-tree-search">
                  <Search className="h-3.5 w-3.5" />
                  <input
                    value={treeQ}
                    onChange={(e) => setTreeQ(e.target.value)}
                    placeholder="搜索章节标题"
                    aria-label="搜索章节标题"
                  />
                </div>
                {treeQ.trim() && (
                  <p className="mtw-filterinfo">匹配 {filtered.hits} 个章节（已全展开）</p>
                )}
                <OutlineTree
                  nodes={filtered.nodes}
                  checked={checked}
                  onToggle={toggleNode}
                  expanded={expanded}
                  onToggleExpand={toggleExpand}
                  onPreview={setPreviewKey}
                  previewKey={previewKey}
                  filtering={Boolean(fileQ.trim())}
                  fileBlocks={pickerBlocks}
                />
              </div>
              <div className="mtw-picker-preview">
                {previewNode ? (
                  <>
                    <div className="mtw-pv-head">
                      <span className="mtw-range-tag">L{pvStart}-L{pvEnd}</span>
                      <span className="mtw-pv-title">{previewNode['标题'] || '（无标题）'}</span>
                      {pvClamped && pvMode !== 'original' && (
                        <span className="mtw-pv-clampnote">大章节，仅预览前 2000 行</span>
                      )}
                      {originalSource && (
                        <span className="mtw-seg-slot">
                          <PreviewSeg mode={pvMode} onChange={setPvMode} />
                        </span>
                      )}
                    </div>
                    <div className="mtw-pv-body">
                      {pvMode === 'original' && originalSource ? (
                        <OriginalView key={originalSource.id} source={originalSource} />
                      ) : (
                        <LinePreview
                          sections={pvContent?.sections}
                          loading={pvLoading}
                          error={pvError}
                          maxLines={pvClamped ? 2000 : undefined}
                        />
                      )}
                    </div>
                  </>
                ) : (
                  <div className="mtw-preview-state">点左侧章节标题预览内容</div>
                )}
              </div>
            </div>
            <div className="mtw-picker-bar">
              <span className="mtw-sel-info">
                已选 <b>{checkedRanges.length}</b> 个区间
              </span>
              <span className="mtw-sel-ranges">
                {checkedRanges.length ? rangesStr(checkedRanges) : '在左侧勾选章节'}
              </span>
              <Button size="sm" className="mtw-bar-btn" disabled={!checkedRanges.length} onClick={() => setCreating(true)}>
                <Plus className="h-3.5 w-3.5" />
                生成素材块
              </Button>
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="mtw">
      {/* 左栏：文件 */}
      <section className="mtw-files">
        <div className="mtw-head" data-tauri-drag-region>
          <span className="kb-title" data-tauri-drag-region>写作素材库</span>
          <span className="mtw-head-sub" data-tauri-drag-region title="历史标书/范文里值得复用的章节">
            历史标书/范文里值得复用的章节
          </span>
        </div>
        <div className="mtw-search">
          <Search className="h-3.5 w-3.5" />
          <input
            value={fileQ}
            onChange={(e) => setFileQ(e.target.value)}
            placeholder="搜索文件名"
            aria-label="搜索文件名"
          />
        </div>
        <div className="mtw-scroll">{renderFileList}</div>
        <div className="mtw-files-foot">
          <Button size="sm" className="mtw-upload-btn" disabled={!!uploading} onClick={() => fileInput.current?.click()}>
            <Upload className="h-3.5 w-3.5" />
            上传文件
          </Button>
          <div className="mtw-foot-hint">
            仅收 .docx——历史标书原文，图表可整体拷贝；单个不超过 100MB
          </div>
          <div className="mtw-foot-note">
            素材仅供写法参考——数字与承诺须按本次招标重新核对；拷贝修订后请检查是否残留原公司名称
          </div>
        </div>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept=".docx"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void onUpload(f)
            e.target.value = ''
          }}
        />
      </section>

      {/* 中栏：素材块 */}
      <section className="mtw-blocks">
        <div className="mtw-head" data-tauri-drag-region>
          <div className="mtw-blocks-toolbar">
            <span className="mtw-blocks-title" data-tauri-drag-region title={scope === 'all' ? '全部素材' : activeFile?.file_name}>
              {scope === 'all' ? '全部素材' : activeFile?.file_name ?? '素材块'}
            </span>
            <span className="mtw-count">{visibleBlocks.length} 个</span>
            <select
              className="mtw-sort"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              aria-label="排序方式"
            >
              <option value="range">按章节顺序</option>
              <option value="chars">按字数</option>
              <option value="used">按引用</option>
            </select>
          </div>
        </div>
        <div className="mtw-searchrow">
          <div className="mtw-search">
            <Search className="h-3.5 w-3.5" />
            <input
              value={blockQ}
              onChange={(e) => setBlockQ(e.target.value)}
              placeholder="搜索标题 / 备注 / 正文"
              aria-label="搜索素材块"
            />
            {searching && <Loader variant="dots" size="xs" tone="muted" />}
          </div>
          <Button
            size="sm"
            variant="outline"
            className="mtw-new-btn"
            disabled={!canNewBlock}
            title={
              canNewBlock
                ? '从目录树勾选章节，建一个新素材块'
                : scope === 'all'
                  ? '先在左侧选择一份文件'
                  : '文件解析完成后可新建'
            }
            onClick={() => activeFile && enterPicker(activeFile)}
          >
            <Plus className="h-3.5 w-3.5" />
            新建素材
          </Button>
          {/* 禁用原因常驻可见（2026-09-23 A3a）：只藏在 hover title 里，用户看到的就是
              一个按不动的灰按钮 */}
          {!canNewBlock && !pickerOpen && (
            <span className="shrink-0 text-xs text-muted-foreground">
              {scope === 'all' ? '先在左侧选择一份文件' : '文件解析完成后可新建'}
            </span>
          )}
        </div>
        <div className="mtw-scroll">{renderBlockList}</div>
      </section>

      {/* 右栏：素材块详情（挑章节是覆盖层，不再占详情区） */}
      <section className="mtw-detail">
        {renderDetailBlock()}
      </section>

      {pickerOpen && pickerFile && (
        <DrawerShell
          /* ESC 双层兜底：确认弹窗与抽屉都在 window 上听 Escape，一次按键两边都触发
             ——抽屉让位，先关确认弹窗，第二次 ESC 才关抽屉 */
          onClose={() => {
            if (!creating) setPickerOpen(false)
          }}
        >
          {renderPicker()}
        </DrawerShell>
      )}

      {creating && pickerFile && (
        <ModalShell onClose={() => setCreating(false)} cardClassName="w-[min(92vw,560px)]">
          <div className="mt-modal">
            <div className="mt-modal-head">生成素材块</div>
            <div className="mt-modal-body">
              {dup.exact.map((b) => (
                <p key={b.id} className="mt-dup-warn">
                  与已有素材块《{b.title}》区间完全相同——如非有意重复，建议返回调整勾选
                </p>
              ))}
              {dup.partial.map((b) => (
                <p key={b.id} className="mt-dup-hint">
                  与《{b.title}》区间部分重叠
                </p>
              ))}
              <div className="mt-modal-ranges">
                {pickerFile.file_name} · {rangesStr(checkedRanges)}（{checkedRanges.length} 段）
              </div>
              <label className="mt-modal-label">素材块标题</label>
              <input
                className="mt-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="默认取首个勾选章节名"
                autoFocus
              />
              <label className="mt-modal-label">
                备注<span className="mt-modal-label-sub">（进检索——写适用场景/亮点，帮助 AI 挑对素材）</span>
              </label>
              <textarea
                className="mt-textarea"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={4}
                placeholder="如「政务云表单管理章，写法成熟；数字为 2023 年口径须重核」"
              />
            </div>
            <div className="mt-modal-foot">
              <Button size="sm" variant="outline" onClick={() => setCreating(false)}>
                取消
              </Button>
              <Button size="sm" disabled={createBlock.isPending} onClick={() => void submitBlock()}>
                {createBlock.isPending ? '创建中…' : '创建素材块'}
              </Button>
            </div>
          </div>
        </ModalShell>
      )}
    </div>
  )
}
