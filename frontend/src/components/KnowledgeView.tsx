/**
 * 知识库主视图（2026-09-08 重设计）：左栏 = 搜索（防抖，范围含内容说明与
 * 检索问题）+ 分类下拉 + 待确认胶囊 + 文件平铺列表；右区 = 大空态（上传 CTA）
 * 或条目详情（components/kb/）。上传走 XHR 进度 + 拖拽。
 * 信息表单有未保存修改时，切条目/切 tab 弹确认（放弃/继续）——不加锁。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Search, TriangleAlert, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ModalShell } from '@/components/ui/ModalShell'
import { uploadKbFile } from '@/api/client'
import { fileExtIcon } from '@/artifacts/registry'
import { Loader } from '@/components/ai/Loader'
import { useKbItems, useKbTypes } from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { cn, formatRelativeTime } from '@/lib/utils'
import { ItemDetail, type DetailTab } from '@/components/kb/ItemDetail'
import { KbHeroEmpty, StatusDot, statusText } from '@/components/kb/kbShared'

interface UploadState {
  id: number
  name: string
  percent: number
}

type PendingNav = { type: 'tab'; to: DetailTab } | { type: 'select'; id: string }

export function KnowledgeView({ onGoLibrary }: { onGoLibrary?: () => void }) {
  const { data, isLoading } = useKbItems()
  const items = data?.items ?? []
  const { data: typeInfo } = useKbTypes()
  const types = typeInfo?.types ?? []
  const { toast } = useToast()
  const qc = useQueryClient()
  const [filter, setFilter] = useState<'all' | 'pending'>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<DetailTab>('content')
  const [infoDirty, setInfoDirty] = useState(false)
  const [pendingNav, setPendingNav] = useState<PendingNav | null>(null)
  const [uploads, setUploads] = useState<UploadState[]>([])
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const uploadIdRef = useRef(0)

  // 搜索防抖：输入即时回显，过滤 300ms 后生效（含说明/问题的过滤较重）
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(query), 300)
    return () => window.clearTimeout(t)
  }, [query])

  const pending = items.filter((it) => it.review_status === 'pending_review')
  const typeCodes = new Set(types.map((t) => t.code))
  const hasOther = items.some((it) => !typeCodes.has(it.doc_type ?? 'other'))
  const filtered = useMemo(() => {
    const list = filter === 'pending' ? pending : items
    let scoped = typeFilter === 'all' ? list : list.filter((it) => (it.doc_type ?? 'other') === typeFilter)
    const q = debounced.trim().toLowerCase()
    if (q) {
      scoped = scoped.filter((it) => {
        if (it.file_name.toLowerCase().includes(q) || it.title.toLowerCase().includes(q)) return true
        const basis = it.business ?? it.suggested
        if (basis?.statement?.toLowerCase().includes(q)) return true
        return (basis?.questions ?? []).some((x) => x.toLowerCase().includes(q))
      })
    }
    return scoped
  }, [items, pending, filter, typeFilter, debounced])

  const selected = items.find((it) => it.id === selectedId) ?? null

  // ===== 脏状态守卫：信息 tab 有未保存修改时，切 tab / 切条目先问一声 =====
  const applyNav = (nav: PendingNav) => {
    if (nav.type === 'tab') setTab(nav.to)
    else {
      setSelectedId(nav.id)
      setTab('content')
    }
  }
  const guardedTab = (t: DetailTab) => {
    if (infoDirty && tab === 'info' && t !== 'info') setPendingNav({ type: 'tab', to: t })
    else setTab(t)
  }
  const guardedSelect = (id: string) => {
    if (infoDirty && id !== selectedId) setPendingNav({ type: 'select', id })
    else {
      setSelectedId(id)
      setTab('content')
    }
  }
  const discardNav = () => {
    if (!pendingNav) return
    setInfoDirty(false)
    applyNav(pendingNav)
    setPendingNav(null)
  }
  useEffect(() => {
    if (!selected) setInfoDirty(false)
  }, [selected])

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

  const emptyText = debounced.trim()
    ? `没有匹配「${debounced.trim()}」的资料`
    : filter === 'pending'
      ? '没有待确认的资料'
      : typeFilter !== 'all'
        ? '该分类下暂无资料'
        : '没有符合条件的资料'

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

      {/* ===== 左栏：搜索 + 筛选 + 文件平铺列表 ===== */}
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
          <span
            className="kb-head-sub"
            data-tauri-drag-region
            title="公司资料——AI 引用的「我们有什么、做过什么」都从这里查；历史标书只作业绩候选，写法参考请去写作素材库"
          >
            公司资料——「我们有什么、做过什么」都从这里查
          </span>
        </div>
        <div className="kb-search">
          <Search className="h-3.5 w-3.5" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索文件名、说明或检索问题" />
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
                onClick={() => guardedSelect(it.id)}
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
                  <span className="kb-sub">
                    {busy
                      ? statusText(it)
                      : `${it.doc_type_name} · ${formatRelativeTime(it.created_at)}`}
                  </span>
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

        {/* 上传入口与写作素材库同款：列表底部通栏主按钮 + 格式提示 */}
        <div className="kb-side-foot">
          <Button size="sm" className="kb-upload-btn" onClick={() => fileInputRef.current?.click()}>
            <Upload className="h-3.5 w-3.5" />
            上传公司资料
          </Button>
          <div className="kb-foot-hint">支持 .docx / .pdf / .txt / .md / .doc / 图片，单个不超过 100MB</div>
        </div>
      </aside>

      {/* ===== 右区：大空态 / 条目详情 ===== */}
      <section className="kb-main">
        {selected ? (
          <ItemDetail
            key={selected.id}
            item={selected}
            types={types}
            tab={tab}
            onTab={guardedTab}
            onBeforeDelete={() => setSelectedId(null)}
            onDirtyChange={setInfoDirty}
          />
        ) : items.length === 0 && !isLoading ? (
          <KbHeroEmpty
            onUpload={() => fileInputRef.current?.click()}
            onGoLibrary={onGoLibrary}
          />
        ) : (
          <div className="kb-main-empty">
            <p>从左侧选择一份资料查看详情</p>
            <p className="text-xs text-muted-foreground">
              AI 已自动整理类型、说明与关键信息；待确认条目会有橙色标记
            </p>
          </div>
        )}
      </section>

      {pendingNav && (
        <ModalShell onClose={() => setPendingNav(null)} cardClassName="w-[min(92vw,380px)]">
          <div className="p-5">
            <p className="text-sm font-semibold">有未保存的修改</p>
            <p className="mt-1 text-xs text-muted-foreground">离开后这些修改不会被保存。</p>
            <div className="mt-4 flex justify-end gap-2">
              <Button size="sm" variant="outline" onClick={() => setPendingNav(null)}>
                继续编辑
              </Button>
              <Button size="sm" variant="destructive" onClick={discardNav}>
                放弃修改
              </Button>
            </div>
          </div>
        </ModalShell>
      )}
    </div>
  )
}
