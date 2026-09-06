import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import {
  BookText,
  Copy,
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
  type KbParseMeta,
  type KbTypePayload,
} from '@/api/client'
import { fileExtIcon } from '@/artifacts/registry'
import { Loader } from '@/components/ai/Loader'
import { mdRemarkPlugins } from '@/lib/markdown'
import { markdownComponents } from '@/components/ai/MemoMarkdown'
import {
  useConfirmMetadata,
  useDeleteKbItem,
  useKbContent,
  useKbItemImages,
  useKbItems,
  useKbTypes,
  useRetriggerKbItem,
} from '@/hooks/useKnowledge'
import { KbImage } from '@/components/KbImage'
import { useToast } from '@/context/Toast'
import { cn } from '@/lib/utils'

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp'])

type DetailTab = 'content' | 'info'

/** 状态点：解析/整理中转圈 / 待确认橙 / 已确认绿 / 失败红 */
function StatusDot({ item }: { item: KbItem }) {
  if (item.parse_status === 'pending' || item.parse_status === 'parsing' || item.extract_status === 'running') {
    return <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
  }
  if (item.parse_status === 'failed') return <span className="kb-dot kb-dot--error" title={item.error ?? ''} />
  if (item.review_status === 'pending_review') return <span className="kb-dot kb-dot--warn" title="待确认" />
  return <span className="kb-dot kb-dot--ok" title="已确认" />
}

/** 状态行文案：能力档位 + 进行中进度（不再裸转圈）。 */
function statusText(item: KbItem): string {
  if (item.parse_status === 'pending' || item.parse_status === 'parsing')
    return item.progress ?? '解析中…'
  if (item.extract_status === 'running') return item.progress ?? '整理中…'
  if (item.parse_status === 'failed') return '解析失败'
  return item.doc_type_name
}

const WARN_CONVERSIONS = new Set([
  'docx-numbered',
  'pdf-numbered',
  'pdf-plain',
  'pdf-fontsize',
  'vision-unavailable',
])

function ParseMetaBar({ meta }: { meta?: KbParseMeta | null }) {
  if (!meta) return null
  const chips: string[] = []
  if (meta.chars != null) chips.push(`${meta.chars.toLocaleString()} 字符`)
  if (meta.headings != null) chips.push(`${meta.headings} 个标题`)
  if (meta.tables != null) chips.push(`${meta.tables} 个表格`)
  if (meta.pages != null) chips.push(`${meta.pages} 页`)
  if (meta.image_count != null && meta.image_count > 0) chips.push(`${meta.image_count} 张图片`)
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

/** 时间边界警示条（sidecar 动态计算：过期/临期/陈旧）。 */
function FreshnessBar({ item }: { item: KbItem }) {
  if (!item.freshness?.length) return null
  return (
    <div className="kb-freshness">
      {item.freshness.map((f) => (
        <span key={f.kind} className={cn('kb-freshness-item', f.kind === 'expired' && 'kb-freshness-item--expired')}>
          <TriangleAlert className="h-3 w-3 shrink-0" />
          {f.label}
        </span>
      ))}
    </div>
  )
}

/** 内容说明卡（v3）：AI 自由提取的带锚点要点——事实类文件的语义入口。 */
function StatementCard({ item }: { item: KbItem }) {
  const basis = item.business ?? item.suggested
  const statement = basis?.statement?.trim()
  if (!statement) return null
  const confirmed = Boolean(item.business?.statement?.trim())
  return (
    <div className="kb-statement">
      <div className="kb-statement-head">
        <BookText className="h-3.5 w-3.5 shrink-0" />
        <span className="kb-statement-title">内容说明</span>
        <span className={cn('kb-statement-tag', confirmed && 'kb-statement-tag--confirmed')}>
          {confirmed ? '已确认' : 'AI 整理·数字须回原文核对'}
        </span>
      </div>
      <p className="kb-statement-body">{statement}</p>
    </div>
  )
}

const TRUNCATE_CHARS = 8000

function MarkdownPreview({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState<'ok' | 'fail' | null>(null)
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
  const types = typeInfo?.types ?? []
  const { toast } = useToast()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<'all' | 'pending'>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<DetailTab>('content')
  const [uploads, setUploads] = useState<UploadState[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadIdRef = useRef(0)

  const pending = items.filter((it) => it.review_status === 'pending_review')
  const typeCodes = new Set(types.map((t) => t.code))
  const hasOther = items.some((it) => !typeCodes.has(it.doc_type ?? 'other'))
  const filtered = useMemo(() => {
    const list = filter === 'pending' ? pending : items
    let scoped = typeFilter === 'all' ? list : list.filter((it) => (it.doc_type ?? 'other') === typeFilter)
    if (query.trim()) {
      const q = query.trim().toLowerCase()
      scoped = scoped.filter((it) => it.file_name.toLowerCase().includes(q) || it.title.toLowerCase().includes(q))
    }
    return scoped
  }, [items, pending, filter, typeFilter, query])

  const selected = items.find((it) => it.id === selectedId) ?? null

  const doUpload = async (files: FileList | File[]) => {
    const list = Array.from(files)
    if (list.length === 0) return
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

  const emptyText = query.trim()
    ? `没有匹配「${query.trim()}」的资料`
    : filter === 'pending'
      ? '没有待确认的资料'
      : typeFilter !== 'all'
        ? '该分类下暂无资料'
        : '知识库还没有资料——上传资质证书、合同案例、历史标书等；挑章节建写作素材请到「写作素材库」'

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

      {/* ===== 左栏：角色分组 + 搜索 + 类型分组列表 ===== */}
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

        <div className="kb-filter-row">
          <select
            className="kb-filter"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            aria-label="分类筛选"
          >
            <option value="all">全部分类</option>
            {types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
            {hasOther && <option value="other">其他</option>}
          </select>
          <button
            type="button"
            className={cn('kb-pill', filter === 'pending' && 'kb-pill--active')}
            onClick={() => setFilter(filter === 'pending' ? 'all' : 'pending')}
            title="只看待确认的资料"
          >
            <TriangleAlert className="h-3.5 w-3.5" />
            待确认
            {pending.length > 0 && <span className="kb-count kb-count--warn">{pending.length}</span>}
          </button>
        </div>

        {uploads.map((u) => (
          <div key={u.id} className="kb-upload-row">
            <span className="truncate">{u.name}</span>
            <span className="kb-upload-pct">{u.percent}%</span>
          </div>
        ))}

        <div className="kb-groups">
          {filtered.map((it) => {
            const expired = it.freshness?.some((f) => f.kind === 'expired')
            const busy =
              it.parse_status === 'pending' ||
              it.parse_status === 'parsing' ||
              it.extract_status === 'running'
            return (
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
                  return <span className={`ft-ico ${ico.cls}`}>{ico.mark}</span>
                })()}
                <span className="kb-file-col">
                  <span className="kb-file-name">
                    {it.file_name}
                    {expired && <span className="kb-expired-tag">过期</span>}
                  </span>
                  {busy && it.progress ? (
                    <span className="kb-sub">{it.progress}</span>
                  ) : (
                    !busy && <span className="kb-sub">{it.doc_type_name}</span>
                  )}
                </span>
                <StatusDot item={it} />
              </button>
            )
          })}
          {filtered.length === 0 &&
            (isLoading ? (
              <div className="kb-empty">
                <span className="inline-flex items-center gap-1.5">
                  <Loader variant="classic" size="sm" tone="muted" />
                  加载中…
                </span>
              </div>
            ) : (
              <div className="kb-empty">{emptyText}</div>
            ))}
        </div>
      </aside>

      {/* ===== 右区：内容 / 信息 ===== */}
      <section className="kb-main">
        {selected ? (
          <ItemDetail
            key={selected.id}
            item={selected}
            types={types}
            tab={tab}
            onTab={setTab}
            onBeforeDelete={() => setSelectedId(null)}
          />
        ) : (
          <div className="kb-main-empty">
            <p>知识库——上传公司资料与历史标书，写标书时 AI 自动检索引用</p>
            <p className="text-xs text-muted-foreground">
              上传不需要选择分类，AI 会自动识别类型并决定处理深度；待确认条目会在左侧标记
            </p>
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
  types: KbTypePayload[]
  tab: DetailTab
  onTab: (t: DetailTab) => void
  onBeforeDelete: () => void
}) {
  const { data: content } = useKbContent(item.id)
  const { data: imagesData } = useKbItemImages(item.id)
  const retrigger = useRetriggerKbItem()
  const del = useDeleteKbItem()
  const { toast } = useToast()
  const [imgUrl, setImgUrl] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const isImage = IMAGE_EXTS.has(item.ext.toLowerCase())
  const busy =
    item.parse_status === 'pending' || item.parse_status === 'parsing' || item.extract_status === 'running'

  useEffect(() => {
    setImgUrl(null)
    // 局部变量而非 state 读值：cleanup 闭包共享本变量，revoke 到的是 fetch 完成后的
    // 真实 URL（读 state 的旧闭包恒拿到 null，objectURL 从不被释放——每看一张图泄一张）
    let url: string | null = null
    if (isImage && item.md_ready === false) {
      void fetchKbItemRaw(item.id)
        .then((u) => {
          url = u
          setImgUrl(u)
        })
        .catch(() => setImgUrl(null))
    }
    return () => {
      if (url) URL.revokeObjectURL(url)
    }
  }, [item.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const parsing = item.parse_status === 'pending' || item.parse_status === 'parsing'
  const extracting = item.extract_status === 'running'

  return (
    <div className="kb-detail">
      <header className="kb-detail-head">
        <div className="min-w-0">
          <div className="kb-detail-title">{item.file_name}</div>
          <div className="kb-detail-meta">
            {busy ? (
              <span className="text-muted-foreground">{statusText(item)}</span>
            ) : (
            <span>{item.doc_type_name}</span>
            )}
            {item.review_status === 'confirmed' && <span className="text-success">已确认</span>}
            {item.review_status === 'pending_review' && !busy && (
              <span className="text-warning">待确认</span>
            )}
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
              title="重新解析与识别（覆盖建议信息，不动已确认内容）"
              onClick={() => {
                void retrigger
                  .mutateAsync(item.id)
                  .then(() => toast('已重新触发解析与识别', 'info'))
                  .catch((e) => toast(e instanceof Error ? e.message : '重新识别失败', 'error'))
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

      {item.parse_status === 'failed' && <div className="kb-error-bar">解析失败：{item.error}</div>}
      <FreshnessBar item={item} />

      <nav className="kb-tabs">
        <button type="button" className={cn('kb-tab', tab === 'content' && 'kb-tab--active')} onClick={() => onTab('content')}>
          内容
        </button>
        <button type="button" className={cn('kb-tab', tab === 'info' && 'kb-tab--active')} onClick={() => onTab('info')}>
          信息{item.review_status === 'pending_review' && !busy ? '（待确认）' : ''}
        </button>
      </nav>

      {tab === 'content' ? (
        <div className="kb-content">
          <ParseMetaBar meta={content?.meta} />
          <StatementCard item={item} />
          {isImage && imgUrl ? (
            <img src={imgUrl} alt={item.file_name} className="kb-image" />
          ) : content?.content ? (
            <MarkdownPreview content={content.content} />
          ) : busy ? (
            <div className="kb-main-empty">
              <Loader variant="classic" size="md" tone="muted" />
              <p>{statusText(item)}</p>
            </div>
          ) : (
            <div className="kb-main-empty">
              <p>无文本内容</p>
              <p className="text-xs text-muted-foreground">
                {isImage ? '图片原件可在「信息」页确认识别结果，或配置支持图片输入的模型后点「重新识别」' : '可点「重新识别」重试'}
              </p>
            </div>
          )}
          {(imagesData?.images?.length ?? 0) > 0 && (
            <details className="kb-images-fold">
              <summary>本文档图片 {imagesData!.images.length} 张（证书扫描/架构图等，仅供查看）</summary>
              <div className="kb-images-grid">
                {imagesData!.images.map((img) => (
                  <KbImage key={img.name} itemId={item.id} imagePath={img.name} alt={img.name} />
                ))}
              </div>
            </details>
          )}
        </div>
      ) : (
        <InfoForm item={item} types={types} />
      )}
    </div>
  )
}

/** 信息确认表单：内容说明编辑 + 时间锚点字段 + 类型（按事实/写法分组）+ 自由字段。 */
function InfoForm({ item, types }: { item: KbItem; types: KbTypePayload[] }) {
  const confirm = useConfirmMetadata()
  const { toast } = useToast()
  const basis = item.business ?? item.suggested
  const [docType, setDocType] = useState<string>(basis?.doc_type ?? item.doc_type ?? 'other')
  const [statement, setStatement] = useState(basis?.statement ?? '')
  const [values, setValues] = useState<Record<string, string>>(() => initValues(basis))
  useEffect(() => {
    setDocType(basis?.doc_type ?? item.doc_type ?? 'other')
    setStatement(basis?.statement ?? '')
    setValues(initValues(basis))
  }, [item.id, item.suggested, item.business]) // eslint-disable-line react-hooks/exhaustive-deps

  const labels = useKbTypes().data?.field_labels ?? {}
  const typeDef = types.find((t) => t.code === docType)
  const fieldKeys = [
    ...new Set([...(typeDef?.time_fields ?? []), 'project_name', 'client', ...Object.keys(values)]),
  ]
  const sources = basis?.fields ?? {}

  const save = async () => {
    try {
      await confirm.mutateAsync({
        id: item.id,
        body: { doc_type: docType, statement: statement.trim() || undefined, fields: values },
      })
      toast('已确认', 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : '保存失败', 'error')
    }
  }

  return (
    <div className="kb-info">
      <div className="kb-info-form">
        {basis && !item.business && (
          <p className="kb-info-warn">以下为 AI 识别建议，请核对后确认；确认后不会被自动覆盖</p>
        )}
        {item.extract_status === 'failed' && (
          <p className="kb-info-warn">自动识别失败（{item.error}）——可点「重新识别」或直接手动填写</p>
        )}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">资料类型</label>
          <select className="kb-select" value={docType} onChange={(e) => setDocType(e.target.value)}>
            {types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">内容说明（供检索与写作引用）</label>
          <textarea
            className="kb-statement-input"
            value={statement}
            onChange={(e) => setStatement(e.target.value)}
            rows={5}
            placeholder="一份说明（关键数字/编号/范围逐条列出，附（第N页）出处）——留空则沿用 AI 整理版"
          />
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
    </div>
  )
}

function initValues(basis: KbItem['suggested']): Record<string, string> {
  const init: Record<string, string> = {}
  for (const [k, v] of Object.entries(basis?.fields ?? {})) init[k] = v?.value ?? ''
  for (const [k, v] of Object.entries(basis?.extra ?? {})) init[k] = v?.value ?? ''
  return init
}
