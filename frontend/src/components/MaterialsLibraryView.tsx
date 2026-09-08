import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  FileText,
  ListChecks,
  Plus,
  Search,
  Trash2,
  Upload,
} from 'lucide-react'
import type { MtBlock, MtFile, MtOutlineNode } from '@/api/client'
import { reparseMtFile, uploadMtFile } from '@/api/client'
import { Button } from '@/components/ui/button'
import { ModalShell } from '@/components/ui/ModalShell'
import { Loader } from '@/components/ai/Loader'
import {
  useCreateMtBlock,
  useDeleteMtBlock,
  useDeleteMtFile,
  useMtBlockContent,
  useMtBlocks,
  useMtFiles,
  useMtOutline,
  useUpdateMtBlock,
} from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { filterOutline, nodeInBlock, overlappingBlocks } from '@/lib/materialsBlocks'
import { cn, formatRelativeTime } from '@/lib/utils'

type View = 'blocks' | 'files' | 'picker'

/** 区间显示：L12-L40 / L12（多区间顿号连接）。 */
function rangesStr(ranges: number[][] | undefined): string {
  return (ranges ?? [])
    .map(([s, e]) => (e && e !== s ? `L${s}-L${e}` : `L${s}`))
    .join('、')
}

/** 搜索防抖（300ms——每次击键打后端 FTS 太密）。 */
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

/** ============ 挑章节：目录树（全层级复选框 + 折叠 + 已建块标记） ============ */

/** 节点 key（start_line——兄弟不重复，勾选与折叠共用）。 */
function nodeKey(n: MtOutlineNode, depth: number, i: number): string {
  return String(n.start_line ?? `n${depth}-${i}`)
}

/** 收集树的全部「有子节点」key（全部展开用）。 */
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

/** 顶层节点 key（初始展开一级）。 */
function topKeys(nodes: MtOutlineNode[]): Set<string> {
  const out = new Set<string>()
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].children?.length) out.add(nodeKey(nodes[i], 0, i))
  }
  return out
}

/** 节点子树的全部 key（自身 + 全部后代）。 */
function subtreeKeys(node: MtOutlineNode): string[] {
  const keys: string[] = []
  const walk = (n: MtOutlineNode) => {
    if (n.start_line != null) keys.push(String(n.start_line))
    for (const c of n.children ?? []) walk(c)
  }
  walk(node)
  return keys
}

/** 节点勾选三态：all=子树全选 / some=部分（半选框）/ none。 */
function nodeCheckState(node: MtOutlineNode, checked: Set<string>): 'all' | 'some' | 'none' {
  const keys = subtreeKeys(node)
  const picked = keys.filter((k) => checked.has(k)).length
  if (picked === 0) return 'none'
  return picked === keys.length ? 'all' : 'some'
}

function OutlineTree({
  nodes,
  checked,
  onToggle,
  expanded,
  onToggleExpand,
  filtering,
  fileBlocks,
  depth = 0,
}: {
  nodes: MtOutlineNode[]
  checked: Set<string>
  onToggle: (node: MtOutlineNode) => void
  expanded: ReadonlySet<string>
  onToggleExpand: (key: string) => void
  filtering: boolean
  fileBlocks: MtBlock[]
  depth?: number
}) {
  return (
    <div className="mt-tree">
      {nodes.map((n, i) => {
        const key = nodeKey(n, depth, i)
        const state = nodeCheckState(n, checked)
        const on = state !== 'none'
        const hasChildren = Boolean(n.children?.length)
        const open = filtering || expanded.has(key)
        return (
          <div key={key}>
            <div
              className={cn('mt-node', on && 'mt-node--checked')}
              style={{ paddingLeft: 8 + depth * 18 }}
            >
              {hasChildren ? (
                <button
                  type="button"
                  className="mt-node-chev"
                  aria-label={open ? '收起子章节' : '展开子章节'}
                  onClick={() => onToggleExpand(key)}
                >
                  <ChevronDown className={cn('mt-chev-ico', open && 'mt-chev-ico--open')} />
                </button>
              ) : (
                <span className="mt-node-chev mt-node-chev--leaf" />
              )}
              <label className="mt-node-label">
                <input
                  type="checkbox"
                  checked={on}
                  ref={(el) => {
                    if (el) el.indeterminate = state === 'some'
                  }}
                  onChange={() => onToggle(n)}
                />
                <span className="mt-node-title">{n['标题'] || '（无标题）'}</span>
                {nodeInBlock(n, fileBlocks) && <span className="mt-node-badge">已建块</span>}
              </label>
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

/** ============ 素材块卡（标题/备注/来源/区间/引用/内容预览；展开编辑或删） ============ */
function BlockCard({ block, fileId2Name }: { block: MtBlock; fileId2Name: Map<string, string> }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState(block.title)
  const [note, setNote] = useState(block.note)
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const update = useUpdateMtBlock()
  const del = useDeleteMtBlock()
  const content = useMtBlockContent(block.id, open)
  const { toast } = useToast()

  const startEdit = () => {
    setTitle(block.title)
    setNote(block.note ?? '')
    setEditing(true)
  }

  const saveEdit = async () => {
    try {
      await update.mutateAsync({ id: block.id, body: { title: title.trim() || block.title, note } })
      setEditing(false)
    } catch (e) {
      toast(e instanceof Error ? e.message : '保存失败', 'error')
    }
  }

  const onDelete = () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      window.setTimeout(() => setConfirmDelete(false), 3000)
      return
    }
    del.mutate(block.id)
  }

  return (
    <div className={cn('kb-lib-card', open && 'kb-mat-card--open')}>
      <button type="button" className="kb-lib-head" onClick={() => setOpen((v) => !v)}>
        <span className="kb-lib-title">{block.title}</span>
        {(block.use_count ?? 0) > 0 && (
          <span className="mt-usage-badge" title="AI 检索命中与正文注入各计一次">
            AI 引用 {block.use_count} 次
            {block.last_used_at ? ` · ${formatRelativeTime(block.last_used_at)}` : ''}
          </span>
        )}
        <ChevronRight className={cn('kb-chev', open && 'kb-chev--open')} />
      </button>
      <div className="kb-lib-meta">
        <span className="kb-lib-src">
          {fileId2Name.get(block.file_id) ?? ''} · {rangesStr(block.ranges)} · 约{' '}
          {(block.chars ?? 0).toLocaleString()} 字
        </span>
        {!editing && (
          <button type="button" className="kb-mat-action" onClick={startEdit}>
            编辑
          </button>
        )}
        <button type="button" className="kb-mat-action" disabled={del.isPending} onClick={onDelete}>
          <Trash2 className="h-3 w-3" />
          {confirmDelete ? '确认删除？' : '删除'}
        </button>
      </div>
      {block.note && !editing && <div className="kb-lib-path">备注：{block.note}</div>}
      {editing && (
        <div className="mt-note-edit">
          <input
            className="mt-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="素材块标题"
          />
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder="备注（进检索——写适用场景/亮点，如「政务云表单章，写法成熟」）"
          />
          <div className="mt-note-actions">
            <Button size="sm" onClick={() => void saveEdit()} disabled={update.isPending}>
              保存
            </Button>
            <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
              取消
            </Button>
          </div>
        </div>
      )}
      {open && (
        <div className="mt-block-preview">
          {content.isPending ? (
            <div className="mt-preview-state">
              <Loader variant="classic" size="sm" tone="muted" /> 加载内容…
            </div>
          ) : content.isError ? (
            <div className="mt-preview-state">内容加载失败——稍后重试展开</div>
          ) : (content.data?.sections ?? []).length === 0 ? (
            <div className="mt-preview-state">（区间内没有可展示的文本）</div>
          ) : (
            (content.data?.sections ?? []).map((sec) => (
              <div key={`${sec.start}-${sec.end}`} className="mt-preview-section">
                <div className="mt-preview-tag">L{sec.start}-L{sec.end}</div>
                <pre className="mt-preview-text">{sec.text}</pre>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

/** ============ 主视图 ============ */
export function MaterialsLibraryView() {
  const [view, setView] = useState<View>('blocks')
  const [pickerFile, setPickerFile] = useState<MtFile | null>(null)
  const [query, setQuery] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const expandedInit = useRef(false)
  const [title, setTitle] = useState('')
  const [note, setNote] = useState('')
  const [creating, setCreating] = useState(false)
  const [confirmDeleteFile, setConfirmDeleteFile] = useState<string | null>(null)
  const [reparsing, setReparsing] = useState<string | null>(null)
  const [uploading, setUploading] = useState<{ name: string; percent: number } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()
  const { toast } = useToast()

  const debouncedQ = useDebounced(query, 300).trim()
  const { data: filesData } = useMtFiles()
  const { data: allBlocksData } = useMtBlocks()
  // q 非空时才走服务端（FTS 含正文）；q 空 key 与全量一致，react-query 自动去重
  const { data: searchBlocksData, isFetching: searching } = useMtBlocks(debouncedQ || undefined)
  const { data: outlineData } = useMtOutline(view === 'picker' ? pickerFile?.id ?? null : null)
  const createBlock = useCreateMtBlock()
  const delFile = useDeleteMtFile()
  const files = filesData?.files ?? []
  const allBlocks = allBlocksData?.blocks ?? []
  const blocks = debouncedQ ? searchBlocksData?.blocks ?? [] : allBlocks
  const fileId2Name = useMemo(() => new Map(files.map((f) => [f.id, f.file_name])), [files])

  // 文件视图：按文件名本地过滤（搜索全视图生效的一环）
  const shownFiles = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return files
    return files.filter((f) => f.file_name.toLowerCase().includes(q))
  }, [files, query])

  const outline = useMemo(() => outlineData?.outline ?? [], [outlineData])
  const fileBlocks = useMemo(
    () => allBlocks.filter((b) => b.file_id === pickerFile?.id),
    [allBlocks, pickerFile],
  )
  // 树过滤（保祖先链；过滤态强制全展开）
  const filtered = useMemo(
    () => (query.trim() ? filterOutline(outline, query) : { nodes: outline, hits: 0 }),
    [outline, query],
  )

  // outline 到达后初始化展开态（顶层一级展开；只做一次，后续折叠归用户）
  useEffect(() => {
    if (!expandedInit.current && outline.length > 0) {
      expandedInit.current = true
      setExpanded(topKeys(outline))
    }
  }, [outline])

  const onUpload = async (file: File) => {
    // 反馈三段：立即切到文件视图显示「上传中 N%」→ 上传完成刷新列表出现「解析中…」行
    // （refetchInterval 5s 轮询收敛到 ready）→ toast 收尾
    setUploading({ name: file.name, percent: 0 })
    setView('files')
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
    const nodes = outlineData?.outline ?? []
    const out: [number, number][] = []
    const walk = (list: MtOutlineNode[]) => {
      for (const n of list) {
        const state = nodeCheckState(n, checked)
        if (state === 'none') continue
        if (state === 'all' && n.start_line != null && n.end_line != null) {
          // 子树全选=整块一个区间（子区间被包含，不再收集）
          out.push([n.start_line, n.end_line])
          continue
        }
        // 部分选中：下钻取选中的子区间（如整章里摘掉一节 → 多区间拼接）
        if (n.children?.length) walk(n.children)
        else if (n.start_line != null && n.end_line != null) out.push([n.start_line, n.end_line])
      }
    }
    walk(nodes)
    return out.toSorted((a, b) => a[0] - b[0])
  }, [checked, outlineData])

  // 建块前的重复探测（提示不阻断——裁决归用户）
  const dup = useMemo(
    () => overlappingBlocks(checkedRanges, fileBlocks),
    [checkedRanges, fileBlocks],
  )

  const submitBlock = async () => {
    if (!pickerFile || !checkedRanges.length) return
    // 标题默认取首个勾选章节的标题
    const firstStart = checkedRanges[0][0]
    const fallbackTitle =
      (() => {
        let found: string | null = null
        const walk = (list: MtOutlineNode[]) => {
          for (const n of list) {
            if (n.start_line === firstStart && n['标题']) found = n['标题']
            if (found) return
            if (n.children?.length) walk(n.children)
          }
        }
        walk(outlineData?.outline ?? [])
        return found
      })() ?? '未命名素材块'
    try {
      await createBlock.mutateAsync({
        fileId: pickerFile.id,
        body: { title: title.trim() || fallbackTitle, note: note.trim(), ranges: checkedRanges },
      })
      toast('素材块已创建', 'success')
      setCreating(false)
      setChecked(new Set())
      setTitle('')
      setNote('')
      setView('blocks')
    } catch (e) {
      toast(e instanceof Error ? e.message : '创建失败', 'error')
    }
  }

  const enterPicker = (f: MtFile) => {
    setPickerFile(f)
    setChecked(new Set())
    setExpanded(new Set())
    expandedInit.current = false
    setTitle('')
    setNote('')
    setView('picker')
  }

  const onDeleteFile = (f: MtFile) => {
    if (confirmDeleteFile !== f.id) {
      setConfirmDeleteFile(f.id)
      window.setTimeout(() => setConfirmDeleteFile((cur) => (cur === f.id ? null : cur)), 3000)
      return
    }
    setConfirmDeleteFile(null)
    delFile.mutate(f.id)
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

  return (
    <div className="kb-lib">
      <div className="kb-lib-pagehead" data-tauri-drag-region>
        <span className="kb-title" data-tauri-drag-region>写作素材库</span>
        <span className="kb-lib-sub" data-tauri-drag-region>
          上传历史标书/范文 → 勾选值得复用的章节 → 加备注——AI 写标书时检索引用
        </span>
      </div>

      <div className="kb-lib-toolbar">
        <div className="kb-search kb-lib-search">
          <Search className="h-3.5 w-3.5" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索标题 / 备注 / 正文"
          />
          {view === 'blocks' && searching && <Loader variant="dots" size="xs" tone="muted" />}
        </div>
        <div className="mt-view-tabs">
          <button
            type="button"
            className={cn('kb-lib-kind', view === 'blocks' && 'kb-lib-kind--active')}
            onClick={() => setView('blocks')}
          >
            <ListChecks className="h-3.5 w-3.5" />
            素材块 {blocks.length || ''}
          </button>
          <button
            type="button"
            className={cn('kb-lib-kind', (view === 'files' || view === 'picker') && 'kb-lib-kind--active')}
            onClick={() => setView('files')}
          >
            <FileText className="h-3.5 w-3.5" />
            文件 {files.length || ''}
          </button>
        </div>
        <Button size="sm" disabled={!!uploading} onClick={() => fileInput.current?.click()}>
          <Upload className="h-3.5 w-3.5" />
          上传文件
        </Button>
        <input
          ref={fileInput}
          type="file"
          hidden
          accept=".docx,.pdf,.txt,.md,.doc"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void onUpload(f)
            e.target.value = ''
          }}
        />
      </div>

      <div className="kb-lib-list">
        {view === 'blocks' ? (
          blocks.length === 0 ? (
            <div className="kb-empty">
              {query.trim()
                ? '没有匹配的素材——换个关键词（标题/备注/正文都搜）'
                : '还没有素材块——上传历史标书/范文，在目录树上勾选值得复用的章节'}
            </div>
          ) : (
            blocks.map((b) => <BlockCard key={b.id} block={b} fileId2Name={fileId2Name} />)
          )
        ) : view === 'files' ? (
          shownFiles.length === 0 && !uploading ? (
            <div className="kb-empty">
              {query.trim() ? '没有匹配的文件——换个关键词' : '还没有文件——点「上传文件」传历史标书/范文'}
            </div>
          ) : (
            <>
              {uploading && !files.some((f) => f.file_name === uploading.name) && (
                <div className="mt-file-row">
                  <Loader variant="classic" size="sm" tone="muted" />
                  <span className="mt-file-name">{uploading.name}</span>
                  <span className="mt-file-meta">上传中 {uploading.percent}%</span>
                </div>
              )}
              {shownFiles.map((f) => (
              <div key={f.id} className="mt-file-row">
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="mt-file-name">{f.file_name}</span>
                <span className="mt-file-meta">
                  {f.parse_status === 'ready'
                    ? `${f.block_count ?? 0} 个素材块`
                    : f.parse_status === 'failed'
                      ? f.error || '解析失败'
                      : '解析中…'}
                </span>
                {f.parse_status === 'ready' && !f.error && (
                  <Button size="sm" variant="outline" onClick={() => enterPicker(f)}>
                    <ListChecks className="h-3.5 w-3.5" />
                    挑章节
                  </Button>
                )}
                {f.parse_status === 'failed' && (
                  <button
                    type="button"
                    className="kb-mat-action"
                    aria-label={`重新解析 ${f.file_name}`}
                    disabled={reparsing === f.id}
                    onClick={() => void onReparseFile(f)}
                  >
                    重试
                  </button>
                )}
                <button
                  type="button"
                  className="kb-mat-action"
                  aria-label={confirmDeleteFile === f.id
                    ? `确认删除 ${f.file_name}（将连带删除其 ${f.block_count ?? 0} 个素材块）`
                    : `删除 ${f.file_name}（将连带删除其全部素材块）`}
                  title="删除文件会连带删除其全部素材块"
                  disabled={delFile.isPending}
                  onClick={() => onDeleteFile(f)}
                >
                  {confirmDeleteFile === f.id ? '确认删除？' : <Trash2 className="h-3 w-3" />}
                </button>
              </div>
            ))}
            </>
          )
        ) : (
          /* ---- 挑章节视图 ---- */
          <div className="mt-picker">
            <div className="mt-picker-head">
              <button type="button" className="kb-md-action" onClick={() => setView('files')}>
                <ArrowLeft className="h-3.5 w-3.5" />
                返回文件列表
              </button>
              <span className="mt-picker-file">{pickerFile?.file_name}</span>
              <span className="mt-picker-count">已勾选 {checkedRanges.length} 节</span>
              {!query.trim() && outline.length > 0 && (
                <span className="mt-picker-treeops">
                  <button type="button" className="kb-md-action" onClick={() => setExpanded(collectParentKeys(outline))}>
                    全部展开
                  </button>
                  <button type="button" className="kb-md-action" onClick={() => setExpanded(new Set())}>
                    全部收起
                  </button>
                </span>
              )}
            </div>
            {(outline.length ?? 0) === 0 ? (
              <div className="kb-empty">
                {outlineData?.parse_status === 'parsing' || outlineData?.parse_status === 'pending' ? (
                  <>
                    <Loader variant="classic" size="sm" tone="muted" /> 正在解析目录…
                  </>
                ) : query.trim() ? (
                  '没有匹配的章节标题——换个关键词'
                ) : (
                  (outlineData?.error ?? '该文件没有识别到目录结构，无法挑章节')
                )}
              </div>
            ) : (
              <>
                <div className="mt-tree-scroll">
                  {query.trim() && (
                    <p className="mt-tree-filterinfo">匹配 {filtered.hits} 个章节（已全展开）</p>
                  )}
                  <OutlineTree
                    nodes={filtered.nodes}
                    checked={checked}
                    onToggle={toggleNode}
                    expanded={expanded}
                    onToggleExpand={toggleExpand}
                    filtering={Boolean(query.trim())}
                    fileBlocks={fileBlocks}
                  />
                </div>
                <div className="mt-picker-bar">
                  <span className="mt-picker-count">
                    {checkedRanges.length
                      ? `已选 ${checkedRanges.length} 个区间（${rangesStr(checkedRanges)}）`
                      : '未勾选章节'}
                  </span>
                  <Button
                    size="sm"
                    disabled={!checkedRanges.length}
                    onClick={() => setCreating(true)}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    生成素材块
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
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
              <Button
                size="sm"
                disabled={createBlock.isPending}
                onClick={() => void submitBlock()}
              >
                {createBlock.isPending ? '创建中…' : '创建素材块'}
              </Button>
            </div>
          </div>
        </ModalShell>
      )}
      <p className="kb-lib-note">
        <FileText className="h-3 w-3" />
        素材仅供写法参考——数字与承诺须按本次招标重新核对；拷贝修订后请扫描旧机构名残留。仅收录文字章节，图片暂不能建块
      </p>
    </div>
  )
}
