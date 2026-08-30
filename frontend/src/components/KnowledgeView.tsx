import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import {
  ChevronRight,
  Copy,
  FileText,
  Folder,
  FolderOpen,
  Inbox,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  fetchKbItemRaw,
  uploadKbFile,
  type KbItem,
  type KbFieldType,
  type KbParseMeta,
} from '@/api/client'
import { fileExtIcon } from '@/artifacts/registry'
import { Loader } from '@/components/ai/Loader'
import { mdRemarkPlugins } from '@/lib/markdown'
import { markdownComponents } from '@/components/ai/MemoMarkdown'
import {
  useConfirmMetadata,
  useDeleteKbItem,
  useKbContent,
  useKbItems,
  useKbTypes,
  useRetriggerKbItem,
} from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { cn } from '@/lib/utils'

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp'])

/** 条目状态点：解析中转圈 / 待确认橙 / 已确认绿 / 失败红 / 就绪灰 */
function StatusDot({ item }: { item: KbItem }) {
  if (item.parse_status === 'pending' || item.parse_status === 'parsing' || item.extract_status === 'running') {
    return <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
  }
  if (item.parse_status === 'failed') return <span className="kb-dot kb-dot--error" title={item.error ?? ''} />
  if (item.review_status === 'pending_review') return <span className="kb-dot kb-dot--warn" title="待确认" />
  return <span className="kb-dot kb-dot--ok" title="已确认" />
}

/** 启发式/降级解析档：徽章与警示行用琥珀语义色（pdf-fontsize 为旧存量 meta 兼容保留） */
const WARN_CONVERSIONS = new Set([
  'docx-numbered',
  'pdf-numbered',
  'pdf-plain',
  'pdf-fontsize',
  'vision-unavailable',
])

/** 解析概况条：档位徽章 + 数字 chips + 警示（数据来自 meta.json，解析质量摆在明面上） */
function ParseMetaBar({ meta }: { meta?: KbParseMeta | null }) {
  if (!meta) return null
  const chips: string[] = []
  if (meta.chars != null) chips.push(`${meta.chars.toLocaleString()} 字符`)
  if (meta.headings != null) chips.push(`${meta.headings} 个标题`)
  if (meta.tables != null) chips.push(`${meta.tables} 个表格`)
  if (meta.pages != null) chips.push(`${meta.pages} 页`)
  if (meta.scanned_pages?.length) chips.push(`扫描页 ${meta.scanned_pages.length}`)
  return (
    <div className="kb-meta">
      <div className="kb-meta-bar">
        <span
          className={cn('kb-meta-badge', WARN_CONVERSIONS.has(meta.conversion) && 'kb-meta-badge--warn')}
        >
          {meta.conversion_label}
        </span>
        {chips.map((c) => (
          <span key={c} className="kb-meta-chip">
            {c}
          </span>
        ))}
      </div>
      {meta.warnings.map((w) => (
        <div key={w} className="kb-meta-warn">
          <TriangleAlert className="h-3 w-3 shrink-0" />
          <span>{w}</span>
        </div>
      ))}
    </div>
  )
}

/** 超长文档默认截断（回退到最近段落边界，防表格/代码块渲染破相），可展开/收起/复制全文 */
const TRUNCATE_CHARS = 8000

function MarkdownPreview({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null)
  // parse 产物的页码锚点（<!-- p:N -->）是给行号引用用的，渲染层剥掉；
  // 「复制全文」仍复制原始 content（锚点对粘贴出去定位行号有用）
  const clean = content.replace(/<!--[\s\S]*?-->/g, '')
  const isTruncated = clean.length > TRUNCATE_CHARS
  let shown = clean
  if (isTruncated && !expanded) {
    const cut = clean.lastIndexOf('\n\n', TRUNCATE_CHARS)
    shown = cut > TRUNCATE_CHARS * 0.6 ? clean.slice(0, cut) : clean.slice(0, TRUNCATE_CHARS)
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied('ok')
    } catch {
      setCopied('fail')
    }
    window.setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div>
      <ReactMarkdown remarkPlugins={mdRemarkPlugins} components={markdownComponents}>
        {shown}
      </ReactMarkdown>
      {isTruncated && (
        <div className="kb-md-tail">
          <span className="kb-md-count">
            {expanded ? '全文' : '已截断，共'} {clean.length.toLocaleString()} 字符
          </span>
          <button type="button" className="kb-md-action" onClick={() => setExpanded((v) => !v)}>
            {expanded ? '收起' : '查看完整内容'}
          </button>
          <button type="button" className="kb-md-action" onClick={() => void copy()}>
            <Copy className="h-3 w-3" />
            {copied === 'ok' ? '已复制' : copied === 'fail' ? '复制失败' : '复制全文'}
          </button>
        </div>
      )}
    </div>
  )
}

interface UploadState {
  id: number
  name: string
  percent: number
}

export function KnowledgeView() {
  const { data, isLoading } = useKbItems()
  const items = data?.items ?? []
  const { data: typeInfo } = useKbTypes()
  const { toast } = useToast()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<'all' | 'pending'>('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<'content' | 'info'>('content')
  const [uploads, setUploads] = useState<UploadState[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadIdRef = useRef(0)

  const pending = items.filter((it) => it.review_status === 'pending_review')
  const filtered = useMemo(() => {
    let list = filter === 'pending' ? pending : items
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      list = list.filter((it) => it.file_name.toLowerCase().includes(q) || it.title.toLowerCase().includes(q))
    }
    return list
  }, [items, pending, filter, query])

  // 按类型分组（参考图的分组折叠形态）；解析中/未归类条目归「其他」组
  const groups = useMemo(() => {
    const map = new Map<string, KbItem[]>()
    for (const it of filtered) {
      const key = it.doc_type ?? 'other'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(it)
    }
    // 有内容的类型组在前，「其他」组最后
    return [...map.entries()].sort((a, b) => (a[0] === 'other' ? 1 : b[0] === 'other' ? -1 : 0))
  }, [filtered])

  const selected = items.find((it) => it.id === selectedId) ?? null

  const doUpload = async (files: FileList | File[]) => {
    const list = Array.from(files)
    if (list.length === 0) return
    // 全部进度行一次性入列 + 并行上传：串行逐个 await 会让上传区任何时刻只显示
    // 一个文件，用户以为其余文件没被接受；id 做键防同名文件进度互相串
    const entries: UploadState[] = list.map((file) => ({
      id: ++uploadIdRef.current,
      name: file.name,
      percent: 0,
    }))
    setUploads((u) => [...u, ...entries])
    await Promise.all(
      list.map(async (file, i) => {
        const entry = entries[i]
        try {
          const item = await uploadKbFile(file, (p) =>
            setUploads((u) => u.map((x) => (x.id === entry.id ? { ...x, percent: p } : x))),
          )
          // 成功反馈=自动选中新条目：await 列表刷新后再选，右区无空档；
          // 只补空位不抢焦点——正在阅读时不跳走；多文件首个落位即停
          await qc.invalidateQueries({ queryKey: ['kb', 'items'] })
          void qc.invalidateQueries({ queryKey: ['kb', 'badge'] })
          setSelectedId((prev) => prev ?? item.id)
        } catch (e) {
          toast(e instanceof Error ? e.message : '上传失败', 'error')
        } finally {
          setUploads((u) => u.filter((x) => x.id !== entry.id))
        }
      }),
    )
  }

  return (
    <div className={cn('kb-view', dragOver && 'kb-view--drag')} data-tauri-drag-region={false}>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        accept=".docx,.pdf,.txt,.md,.doc,.jpg,.jpeg,.png,.webp,.bmp"
        onChange={(e) => {
          if (e.target.files?.length) void doUpload(e.target.files)
          e.target.value = ''
        }}
      />

      {/* ===== 左栏：搜索 + 分组文件列表（参考图侧栏形态） ===== */}
      <aside
        className="kb-side"
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          if (e.dataTransfer.files?.length) void doUpload(e.dataTransfer.files)
        }}
      >
        <div className="kb-side-head" data-tauri-drag-region>
          <span className="kb-title" data-tauri-drag-region>知识库</span>
          <button type="button" className="kb-add" title="上传资料" onClick={() => fileInputRef.current?.click()}>
            <Plus className="h-4 w-4" />
          </button>
        </div>
        <div className="kb-search">
          <Search className="h-3.5 w-3.5" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索资料" />
        </div>

        <button
          type="button"
          className={cn('kb-nav', filter === 'all' && 'kb-nav--active')}
          onClick={() => setFilter('all')}
        >
          <Inbox className="h-3.5 w-3.5" />
          全部资料
          <span className="kb-count">{items.length}</span>
        </button>
        <button
          type="button"
          className={cn('kb-nav', filter === 'pending' && 'kb-nav--active')}
          onClick={() => setFilter('pending')}
        >
          <FileText className="h-3.5 w-3.5" />
          待确认
          {pending.length > 0 && <span className="kb-count kb-count--warn">{pending.length}</span>}
        </button>

        {uploads.map((u) => (
          <div key={u.id} className="kb-upload-row">
            <span className="truncate">{u.name}</span>
            <span className="kb-upload-pct">{u.percent}%</span>
          </div>
        ))}

        <div className="kb-groups">
          {groups.map(([typeCode, list]) => {
            const t = typeInfo?.types.find((x) => x.code === typeCode)
            const collapsed = collapsedGroups[typeCode] ?? false
            return (
              <div key={typeCode} className="kb-group">
                <button
                  type="button"
                  className="kb-group-head"
                  onClick={() => setCollapsedGroups((g) => ({ ...g, [typeCode]: !collapsed }))}
                >
                  {collapsed ? <Folder className="h-3.5 w-3.5" /> : <FolderOpen className="h-3.5 w-3.5" />}
                  <span className="truncate">{t?.name ?? '其他'}</span>
                  <span className="kb-count">{list.length}</span>
                  <ChevronRight className={cn('kb-chev', !collapsed && 'kb-chev--open')} />
                </button>
                {!collapsed &&
                  list.map((it) => (
                    <button
                      key={it.id}
                      type="button"
                      className={cn('kb-file', selectedId === it.id && 'kb-file--active')}
                      onClick={() => {
                        setSelectedId(it.id)
                        setTab('content')
                      }}
                    >
                      {(() => {
                        const ico = fileExtIcon(it.file_name)
                        return (
                          <span className={`ft-ico ${ico.cls}`}>{ico.mark}</span>
                        )
                      })()}
                      <span className="kb-file-name">{it.file_name}</span>
                      <StatusDot item={it} />
                    </button>
                  ))}
              </div>
            )
          })}
          {groups.length === 0 &&
            (isLoading ? (
              <div className="kb-empty">
                <span className="inline-flex items-center gap-1.5">
                  <Loader variant="classic" size="sm" tone="muted" />
                  加载中…
                </span>
              </div>
            ) : (
              <div className="kb-empty">
                {query.trim()
                  ? `没有匹配「${query.trim()}」的资料`
                  : filter === 'pending'
                    ? '没有待确认的资料'
                    : '暂无资料——点右上 + 或拖拽文件上传'}
              </div>
            ))}
        </div>
      </aside>

      {/* ===== 右区：内容预览 / 信息确认 ===== */}
      <section className="kb-main">
        {selected ? (
          <ItemDetail
            key={selected.id}
            item={selected}
            types={typeInfo?.types ?? []}
            tab={tab}
            onTab={setTab}
            // 删除确认时先卸载详情：content 查询的 observer 退场后再删，
            // 否则 removeQueries 对活跃查询会立即重建重发请求 → 已删条目 404
            onBeforeDelete={() => setSelectedId(null)}
          />
        ) : (
          <div className="kb-main-empty">
            <p>公司资料库——上传资质证书、合同案例、人员证书等资料</p>
            <p className="text-xs text-muted-foreground">上传后自动解析与识别信息，待确认条目会在左侧标记</p>
          </div>
        )}
      </section>
    </div>
  )
}

function ItemDetail({
  item,
  types,
  tab,
  onTab,
  onBeforeDelete,
}: {
  item: KbItem
  types: KbFieldType[]
  tab: 'content' | 'info'
  onTab: (t: 'content' | 'info') => void
  onBeforeDelete: () => void
}) {
  const { data: content } = useKbContent(item.id)
  const retrigger = useRetriggerKbItem()
  const del = useDeleteKbItem()
  const { toast } = useToast()
  const [imgUrl, setImgUrl] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const isImage = IMAGE_EXTS.has(item.ext.toLowerCase())

  useEffect(() => {
    setImgUrl(null)
    if (isImage && item.md_ready === false) {
      // 图片原件预览（VL 降级条目：转写为空，直接看原件）
      void fetchKbItemRaw(item.id)
        .then(setImgUrl)
        .catch(() => setImgUrl(null))
    }
    return () => {
      if (imgUrl) URL.revokeObjectURL(imgUrl)
    }
  }, [item.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // 两阶段分开表达：parsing=文本提取（内容还没有，大转圈合理）；
  // extracting=LLM 信息识别（正文已可读，只是建议信息还在跑）
  const parsing = item.parse_status === 'pending' || item.parse_status === 'parsing'
  const extracting = item.extract_status === 'running'

  return (
    <div className="kb-detail">
      <header className="kb-detail-head">
        <div className="min-w-0">
          <div className="kb-detail-title">{item.file_name}</div>
          <div className="kb-detail-meta">
            {parsing ? (
              <span className="text-muted-foreground">解析中…</span>
            ) : extracting ? (
              <span className="text-muted-foreground">信息识别中…</span>
            ) : (
              <span>{item.doc_type_name}</span>
            )}
            {item.review_status === 'confirmed' && <span className="text-success">已确认</span>}
            {item.review_status === 'pending_review' && item.parse_status === 'ready' && !extracting && (
              <span className="text-warning">待确认</span>
            )}
            {item.extract_status === 'skipped' && <span className="text-muted-foreground">信息未识别（手动填写）</span>}
          </div>
        </div>
        <div className="flex gap-1.5">
          {parsing ? (
            <span className="inline-flex items-center gap-1.5 self-center px-1 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              解析中…
            </span>
          ) : (
            <Button
              size="sm"
              variant="outline"
              className={item.parse_status === 'failed' ? 'text-error' : ''}
              disabled={extracting}
              title={extracting ? '信息识别中，稍候' : '重新解析与识别（覆盖建议信息，不动已确认内容）'}
              onClick={() => {
                void retrigger.mutateAsync(item.id).then(() => toast('已重新触发解析与识别', 'info'))
              }}
            >
              <RefreshCw className={cn('h-3.5 w-3.5', retrigger.isPending && 'animate-spin')} />
              {retrigger.isPending ? '提交中…' : item.parse_status === 'failed' ? '重新解析' : '重新识别'}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            className={!confirmDelete ? 'text-error' : ''}
            onClick={() => {
              if (!confirmDelete) {
                setConfirmDelete(true)
                window.setTimeout(() => setConfirmDelete(false), 3000)
                return
              }
              onBeforeDelete()
              void del.mutateAsync(item.id)
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {confirmDelete ? '确认删除？' : '删除'}
          </Button>
        </div>
      </header>

      {item.parse_status === 'failed' && (
        <div className="kb-error-bar">解析失败：{item.error}</div>
      )}

      <nav className="kb-tabs">
        <button type="button" className={cn('kb-tab', tab === 'content' && 'kb-tab--active')} onClick={() => onTab('content')}>
          内容
        </button>
        <button type="button" className={cn('kb-tab', tab === 'info' && 'kb-tab--active')} onClick={() => onTab('info')}>
          信息{item.review_status === 'pending_review' && !parsing && !extracting ? '（待确认）' : ''}
        </button>
      </nav>

      {tab === 'content' ? (
        <div className="kb-content">
          <ParseMetaBar meta={content?.meta} />
          {isImage && imgUrl ? (
            <img src={imgUrl} alt={item.file_name} className="kb-image" />
          ) : content?.content ? (
            <MarkdownPreview content={content.content} />
          ) : parsing || extracting ? (
            <div className="kb-main-empty">
              <Loader variant="classic" size="md" tone="muted" />
              <p>{parsing ? '正在解析…' : '正在读取…'}</p>
            </div>
          ) : (
            <div className="kb-main-empty">
              <p>无文本内容</p>
              <p className="text-xs text-muted-foreground">
                {isImage ? '图片原件可在「信息」页确认识别结果，或配置支持图片输入的模型后点「重新识别」' : '可点「重新识别」重试'}
              </p>
            </div>
          )}
        </div>
      ) : (
        <InfoForm item={item} types={types} />
      )}
    </div>
  )
}

/** 信息确认表单：类型下拉 + 字段模板（suggested 预填 + source 出处小字）。 */
function InfoForm({ item, types }: { item: KbItem; types: KbFieldType[] }) {
  const confirm = useConfirmMetadata()
  const { toast } = useToast()
  // 已确认用 business 真值，否则用 suggested 预填
  const basis = item.business_metadata ?? item.suggested_metadata
  const [docType, setDocType] = useState<string>(basis?.doc_type ?? item.doc_type ?? 'other')
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {}
    for (const [k, v] of Object.entries(basis?.fields ?? {})) init[k] = v.value ?? ''
    for (const [k, v] of Object.entries(basis?.extra ?? {})) init[k] = v.value ?? ''
    return init
  })
  useEffect(() => {
    const b = item.business_metadata ?? item.suggested_metadata
    setDocType(b?.doc_type ?? item.doc_type ?? 'other')
    const init: Record<string, string> = {}
    for (const [k, v] of Object.entries(b?.fields ?? {})) init[k] = v.value ?? ''
    for (const [k, v] of Object.entries(b?.extra ?? {})) init[k] = v.value ?? ''
    setValues(init)
  }, [item.id, item.suggested_metadata, item.business_metadata]) // eslint-disable-line react-hooks/exhaustive-deps

  const labels = useKbTypes().data?.field_labels ?? {}
  const typeDef = types.find((t) => t.code === docType)
  // 展示字段 = 所选类型模板 ∪ 已有值的字段（suggested 的模板外字段也露出来）
  const fieldKeys = [...new Set([...(typeDef?.fields ?? []), ...Object.keys(values)])]
  const sources = basis?.fields ?? {}

  const save = async () => {
    try {
      await confirm.mutateAsync({
        id: item.id,
        body: { doc_type: docType, fields: values },
      })
      toast('已确认', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : '保存失败', 'error')
    }
  }

  return (
    <div className="kb-info">
      {basis?.summary && <p className="kb-info-summary">识别摘要：{basis.summary}</p>}
      {item.extract_status === 'failed' && (
        <p className="kb-info-warn">自动识别失败（{item.error}）——可点「重新识别」或直接手动填写</p>
      )}
      {item.suggested_metadata && !item.business_metadata && (
        <p className="kb-info-warn">以下为 AI 识别建议，请核对后确认；确认后不会被自动覆盖</p>
      )}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">资料类型</label>
        <select
          className="kb-select"
          value={docType}
          onChange={(e) => setDocType(e.target.value)}
        >
          {types.map((t) => (
            <option key={t.code} value={t.code}>
              {t.name}
            </option>
          ))}
        </select>
      </div>
      {fieldKeys.map((k) => (
        <div key={k} className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            {labels[k] ?? k}
            {sources[k]?.source && <span className="kb-source">（出处：{sources[k].source}）</span>}
          </label>
          <Input
            value={values[k] ?? ''}
            onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
            placeholder="—"
          />
        </div>
      ))}
      <Button size="sm" onClick={save} disabled={confirm.isPending}>
        {item.review_status === 'confirmed' ? '保存修改' : '确认信息'}
      </Button>
    </div>
  )
}
