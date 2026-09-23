/**
 * tender.directory 处理程序（P3：查看 + 编辑闭环）。
 *
 * 查看：响应文件分册 → 目录树（来源徽章/交付形态/概述）→ 来源登记表 → lineage 告警。
 * 编辑：同级拖拽排序 + 改名 + 新增/删除节点（标注字段不可改但整节点保留）。
 * 保存基建走 useAutoSave（2026-09-04 统一）：防抖保存 + content_seq 探测 +
 * 5s 轮询（meta 端点）——查看态静默跟随外部更新，编辑态交用户裁决
 * （拉取最新 / 保留我的=强制覆盖）。发布即覆盖（服务端留恢复点），无租约；
 * 永不静默丢用户编辑；关闭时冲刷挂起保存。
 * 运行期 _id 仅用于树寻址，序列化时剥离、不落盘。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileText,
  History,
  Info,
} from 'lucide-react'
import type { ProcessorProps } from '@/artifacts/registry'
import { getArtifactContent, getArtifactMeta, restoreArtifact, updateArtifactContent } from '@/api/client'
import { cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'
import { useAutoSave } from '@/hooks/useAutoSave'
import { SaveStateBar } from '@/components/editors/SaveStateBar'
import { SourceTraceDialog } from '@/components/processors/SourceTraceDialog'
import { DirectoryEditor } from '@/components/processors/DirectoryEditor'
import { structureSignature, type DirectoryData, type EditDoc, type EditNode } from '@/components/processors/directoryTree'
import { NUMBERING_OPTIONS, numberTree, type NumberedNode, type NumberingValue } from './directoryNumbering'

/** 来源徽章配色（token 派生，暗色自动跟随）：MAND=danger 红 TPL=info 蓝 REQ=brand 青 SCORE=warning 琥珀
 *  （写作指引表格的依据 chips 同款配色，导出共用单源） */
export const BADGE_COLORS: Array<[prefix: string, color: string]> = [
  ['MAND', 'var(--Color-danger)'],
  ['TPL', 'var(--Color-info)'],
  ['REQ', 'var(--Color-brand-primary)'],
  ['SCORE', 'var(--Color-warning)'],
]

export function badgeStyle(id: string): React.CSSProperties {
  const hit = BADGE_COLORS.find(([p]) => id.startsWith(p))
  const color = hit ? hit[1] : 'var(--Color-text-secondary)'
  return { color, background: `color-mix(in srgb, ${color} 12%, var(--Color-bg-canvas))` }
}

/** 四类来源的业务含义（图例用；前缀是系统内部对账编号，不解释用户认不出） */
export const BADGE_LABELS: Record<string, string> = {
  MAND: '资格/强制条款',
  TPL: '格式件（招标方给定）',
  REQ: '商务技术要求',
  SCORE: '评分项',
}

/** 四色徽章图例：写作指引说明段与目录 ⓘ 展开行共用（点击徽章=看登记原文与出处） */
export function BadgeLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
      <span>来源标注（点徽章看原文与出处）：</span>
      {BADGE_COLORS.map(([prefix, color]) => (
        <span key={prefix} className="inline-flex items-center gap-1">
          <span
            className="rounded px-1 py-px text-[10px] font-medium"
            style={{ color, background: `color-mix(in srgb, ${color} 12%, var(--Color-bg-canvas))` }}
          >
            {prefix}
          </span>
          {BADGE_LABELS[prefix]}
        </span>
      ))}
    </div>
  )
}

function parse(raw: string): DirectoryData | null {
  try {
    const data = JSON.parse(raw) as DirectoryData
    return Array.isArray(data.response_documents) ? data : null
  } catch {
    return null
  }
}

/** 树搜索：保留命中节点及其祖先链（命中=目录名称/节点概述含关键词，忽略大小写）。 */
function filterTree(nodes: EditNode[], q: string): { nodes: EditNode[]; hits: number } {
  const out: EditNode[] = []
  let hits = 0
  for (const n of nodes) {
    const self = n.目录名称?.toLowerCase().includes(q) || n.节点概述?.toLowerCase().includes(q)
    const child = filterTree(n.children ?? [], q)
    if (self) hits += 1
    if (self || child.hits > 0) {
      out.push(self ? n : { ...n, children: child.nodes })
      hits += child.hits
    }
  }
  return { nodes: out, hits }
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

// ---------- 主组件 ----------

export function DirectoryProcessor({ artifact, content }: ProcessorProps) {
  const data = useMemo(() => parse(content), [content])
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const [editing, setEditing] = useState(false)
  const [docs, setDocs] = useState<DirectoryData | null>(null)
  // 来源追溯弹窗（查看态徽章点击）与树搜索（命中+祖先链裁剪渲染）
  const [traceId, setTraceId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  // 结构性变更确认条：签名≠已确认基线时拦截保存（提示不阻止，确认后放行并前移基线）
  const [structConfirm, setStructConfirm] = useState(false)

  // refs：保存闭包/树操作需要最新值，避免闭包过期
  const docsRef = useRef<DirectoryData | null>(null)
  const seqRef = useRef(artifact.content_seq)
  const confirmedSigRef = useRef('') // 用户已放行的结构基线（进编辑态重置；确认一次前移一次）
  const pendingSigRef = useRef('') // 触发确认条时的待确认签名
  // 确认条引导（2026-09-23 A2）：点「完成编辑」被拦时闪烁确认条——此前只有 3s toast，
  // 用户看着按钮毫无反应
  const structBannerRef = useRef<HTMLDivElement>(null)
  const [structPulse, setStructPulse] = useState(false)
  docsRef.current = docs

  // 结构回基线=确认条过期（用户撤销了结构性修改）：自动撤条——否则「完成编辑」
  // 会被一条不再适用的确认条永久拦住（2026-09-21 诊断 P1 的过期挂起形态）
  useEffect(() => {
    if (!structConfirm || !docs) return
    if (structureSignature(docs.response_documents ?? []) === confirmedSigRef.current) {
      setStructConfirm(false)
    }
  }, [docs, structConfirm])

  const auto = useAutoSave({
    save: async (force) => {
      const d = docsRef.current
      if (!d) return seqRef.current
      const res = await updateArtifactContent(artifact.artifact_id, stripIds(d), seqRef.current, force)
      seqRef.current = res.content_seq
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
      return res.content_seq
    },
    fetchMeta: async () => (await getArtifactMeta(artifact.artifact_id)).content_seq,
    initialVersion: artifact.content_seq,
    // 结构性变更闸：增删/移动（签名变化）在保存前弹确认条——告知不是门禁，用户放行后不再拦同一结构
    beforeSave: () => {
      const d = docsRef.current
      if (!d) return true
      const sig = structureSignature(d.response_documents ?? [])
      if (sig === confirmedSigRef.current) return true
      pendingSigRef.current = sig
      setStructConfirm(true)
      return false
    },
    onExternalUpdate: (remote) => {
      seqRef.current = remote
      auto.reset(remote)
      // 查看态：content prop 经 react-query invalidate 刷新（编辑态 docs 不动，等裁决）
      void queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    },
  })

  const mutate = (fn: (d: DirectoryData) => void) => {
    setDocs((prev) => {
      if (!prev) return prev
      const next = structuredClone(prev)
      fn(next)
      return next
    })
    auto.markDirty()
  }

  const stopEditing = () => {
    setEditing(false)
    setStructConfirm(false)
  }

  /** 以服务端最新内容作为编辑基底（无本地改动时静默跟随 / 用户选择「拉取最新」） */
  const adoptLatest = async () => {
    try {
      const [{ content: raw }, meta] = await Promise.all([
        getArtifactContent(artifact.artifact_id),
        getArtifactMeta(artifact.artifact_id),
      ])
      const fresh = parse(raw)
      if (!fresh) return
      seqRef.current = meta.content_seq
      setDocs(assignIds(structuredClone(fresh)))
      auto.reset(meta.content_seq)
    } catch {
      /* 探测失败静默，下次轮询再试 */
    }
  }

  const startEdit = () => {
    if (!data) return
    seqRef.current = artifact.content_seq
    auto.reset(artifact.content_seq)
    const clone = assignIds(structuredClone(data))
    // 结构基线重置：编辑会话起点（默认展开前两层在 DirectoryEditor 内初始化）
    confirmedSigRef.current = structureSignature(clone.response_documents ?? [])
    setStructConfirm(false)
    setDocs(clone)
    setEditing(true)
  }

  const exitEdit = async () => {
    // 冲突/结构确认未裁决：留在编辑态由横幅/确认条按钮收尾（此时退出=静默丢用户编辑）
    if (auto.state === 'conflict') {
      toast('内容有冲突待裁决：请先在上方横幅选择「拉取最新」或「保留我的」', 'error')
      return
    }
    if (structConfirm) {
      toast('有结构性修改待确认：请先在确认条选择「继续保存」或「返回修改」', 'error')
      setStructPulse(true)
      structBannerRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      window.setTimeout(() => setStructPulse(false), 1600)
      return
    }
    if (auto.state === 'dirty' && !(await auto.saveNow())) return
    stopEditing()
  }

  /** 结构确认条「继续保存」：前移基线签名后放行本次保存（同一结构不再拦）。 */
  const confirmStructuralSave = () => {
    confirmedSigRef.current = pendingSigRef.current
    setStructConfirm(false)
    void auto.saveNow()
  }

  // 来源追溯的「查看原文上下文」已改为条目内嵌切片（SourceEntryCard→
  // ParseContextBlock，2026-09-09 用户拍板就地展示替代跳转）——旧跳转链删除。

  const handleRestore = async () => {
    try {
      await restoreArtifact(artifact.artifact_id)
      toast('已恢复上一版', 'success')
      await queryClient.invalidateQueries({ queryKey: ['artifacts'] })
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
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
  const q = query.trim().toLowerCase()
  const filtering = !editing && q.length > 0
  let hitCount = 0
  // 查看态渲染（编辑态树由 DirectoryEditor 渲染，见 editing 分支）；cast 说明同下
  const renderDocs = filtering
    ? data.response_documents!.map((doc) => {
        const r = filterTree(doc.directory ?? [], q)
        hitCount += r.hits
        // 查看态渲染只用节点字段；cast 对齐编辑态数组类型（_id 仅编辑态寻址）
        return { ...doc, directory: r.nodes as EditNode[] }
      })
    : data.response_documents!
  // 编号预览（查看态）：先过滤后装饰——过滤保序，编号与全量一致；每册一次 numberTree（首章重起）
  const numberedDocs = renderDocs.map((doc) =>
    numberTree(doc.directory ?? [], data.numbering ?? 'chapter'),
  )

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
          <div className="ml-auto flex items-center gap-2">
            {filtering && (
              <span className="shrink-0 text-xs text-muted-foreground">{hitCount} 个匹配</span>
            )}
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索目录…"
              className="w-40 rounded-md border border-line bg-card px-2 py-1 text-xs focus:border-primary focus:outline-none"
            />
          </div>
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
          <SaveStateBar state={auto.state} lastSavedAt={auto.lastSavedAt} onRetry={() => void auto.saveNow()} />
          <label
            className="ml-auto flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"
            title="编号在生成整本 Word 时套用；此处目录树实时预览编号效果"
          >
            章节编号
            <select
              value={docs?.numbering ?? 'chapter'}
              onChange={(e) =>
                mutate((d) => {
                  d.numbering = e.target.value as NumberingValue
                })
              }
              className="rounded-md border border-line bg-card px-2 py-1 text-xs focus:border-primary focus:outline-none"
            >
              {NUMBERING_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {editing && structConfirm && (
        <div
          ref={structBannerRef}
          className={structPulse ? 'struct-confirm-pulse rounded-md' : undefined}
        >
          <Banner
            tone="warn"
            action={
              <span className="flex shrink-0 gap-1">
                <button
                  type="button"
                  onClick={() => setStructConfirm(false)}
                  className="rounded border border-warning/60 px-2 py-0.5 hover:bg-warning/15"
                >
                  返回修改
                </button>
                <button
                  type="button"
                  onClick={confirmStructuralSave}
                  className="rounded border border-warning/60 bg-warning px-2 py-0.5 font-medium text-warning-foreground hover:opacity-90"
                >
                  继续保存
                </button>
              </span>
            }
          >
            检测到结构性修改（新增/删除/移动节点）——保存后，后续 AI 将以新目录为准继续工作（生成正文等）。纯改名不会触发本提示。
          </Banner>
        </div>
      )}
      {auto.state === 'conflict' && (
        <Banner
          tone="warn"
          action={
            <span className="flex shrink-0 gap-1">
              <button
                type="button"
                onClick={() => void adoptLatest()}
                className="rounded border border-warning/60 px-2 py-0.5 hover:bg-warning/15"
              >
                拉取最新内容
              </button>
              <button
                type="button"
                onClick={() => void auto.saveNow(true)}
                className="rounded border border-warning/60 bg-warning font-medium text-warning-foreground px-2 py-0.5 hover:opacity-90"
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
        <SourceCheckBanner
          unused={unused}
          dangling={dangling}
          registry={data.registry ?? {}}
          onTrace={setTraceId}
        />
      )}

      {data.meta && Object.keys(data.meta).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(data.meta).map(([k, v]) => (
            <span
              key={k}
              title={`${k}：${v}`}
              className="max-w-[320px] truncate rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
            >
              {k}：{v}
            </span>
          ))}
        </div>
      )}

      {editing && docs && (
        <DirectoryEditor
          docs={docs}
          mutate={mutate}
          setDocs={(d) => setDocs(d)}
          markDirty={auto.markDirty}
          numbering={docs.numbering ?? 'chapter'}
        />
      )}

      {!editing &&
        renderDocs.map((doc, idx) => (
          <DocSection
            key={doc.name ?? idx}
            doc={doc}
            numberedList={numberedDocs[idx] ?? []}
            filtering={filtering}
            onTrace={setTraceId}
          />
        ))}

      {registryEntries.length > 0 && <RegistrySection entries={registryEntries} />}

      <SourceTraceDialog
        traceId={traceId}
        entry={traceId ? (data.registry ?? {})[traceId] : undefined}
        onClose={() => setTraceId(null)}
        taskId={artifact.task_id ?? null}
      />
    </div>
  )
}

// ---------- 查看态册卡片（头部 ⓘ 图例 + 收起的编制说明 + 编号预览树） ----------

function DocSection({
  doc,
  numberedList,
  filtering,
  onTrace,
}: {
  doc: EditDoc
  /** 与 doc.directory 同序同构的编号装饰树 */
  numberedList: NumberedNode[]
  filtering: boolean
  onTrace?: (id: string) => void
}) {
  const [legendOpen, setLegendOpen] = useState(false)
  const directory = doc.directory ?? []
  return (
    <section className="rounded-lg border">
      <header className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2">
        <FileText className="h-4 w-4 shrink-0 text-primary" />
        <span className="font-semibold">{doc.name ?? '未命名响应文件'}</span>
        <span className="text-xs text-muted-foreground">{directory.length} 个顶层章节</span>
        <button
          type="button"
          onClick={() => setLegendOpen((v) => !v)}
          className={cn(
            'ml-auto rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground',
            legendOpen && 'text-foreground',
          )}
          aria-label="来源标注说明"
          title="来源标注说明"
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      </header>
      {legendOpen && (
        <div className="border-b px-3 py-1.5">
          <BadgeLegend />
        </div>
      )}
      <ScopeText text={doc.scope} />
      <div className="px-3 py-2">
        {directory.map((node, i) => (
          <TreeNode
            key={filtering ? `q-${i}` : i}
            numbered={numberedList[i] ?? { node, prefix: '', children: [] }}
            depth={0}
            defaultOpen={filtering}
            onTrace={onTrace}
          />
        ))}
      </div>
    </section>
  )
}

/** 编制说明（册级 scope）：AI 的归章解释有价值但不该挡在树前面——默认收起两行，想读再展开。 */
function ScopeText({ text }: { text?: string }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  const clamped = !open && text.length > 90
  return (
    <div className="border-b px-3 py-2 text-xs leading-relaxed text-muted-foreground">
      <div className="flex items-start gap-2">
        <span className="mt-px shrink-0 font-medium text-foreground/60">编制说明</span>
        <div className="min-w-0 flex-1">
          <p className={cn(clamped && 'line-clamp-2')}>{text}</p>
          {text.length > 90 && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="mt-0.5 text-primary hover:underline"
            >
              {open ? '收起' : '展开'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/** 来源核对横幅：完整度信号保留，主文案说人话。展开不只给内部编号（2026-09-23 C1：
 *  「有 4 项要求未安排」却只看到 REQ-31 这种编号，用户无从判断要不要补）——逐行列
 *  要求原文与出处（registry 就在同一产物里），点编号打开原文上下文弹窗。 */
function SourceCheckBanner({
  unused,
  dangling,
  registry,
  onTrace,
}: {
  unused: string[]
  dangling: string[]
  registry: NonNullable<DirectoryData['registry']>
  onTrace: (id: string) => void
}) {
  const [showIds, setShowIds] = useState(false)
  return (
    <Banner
      tone="warn"
      action={
        <button
          type="button"
          onClick={() => setShowIds((v) => !v)}
          className="shrink-0 rounded border border-warning/60 px-2 py-0.5 hover:bg-warning/15"
        >
          {showIds ? '收起详情' : '查看详情'}
        </button>
      }
    >
      {unused.length > 0 && `有 ${unused.length} 项招标要求还没安排进目录章节`}
      {unused.length > 0 && dangling.length > 0 && '；'}
      {dangling.length > 0 && `目录里引用了 ${dangling.length} 个不存在的来源编号`}
      {showIds && (
        <ul className="mt-1.5 block space-y-1">
          {[...unused, ...dangling].map((id) => {
            const entry = registry[id]
            return (
              <li key={id} className="flex flex-wrap items-baseline gap-x-1.5">
                <button
                  type="button"
                  onClick={() => onTrace(id)}
                  title={entry ? '查看原文出处上下文' : '来源登记表缺此项，无法追溯'}
                  className="cursor-pointer break-all font-mono text-xs text-warning hover:underline"
                >
                  {id}
                </button>
                {entry?.text && <span className="text-xs">· {entry.text}</span>}
                {entry?.['出处'] && (
                  <span className="text-xs text-muted-foreground">（{entry['出处']}）</span>
                )}
                {!entry && <span className="text-xs text-muted-foreground">（登记表缺此项）</span>}
              </li>
            )
          })}
        </ul>
      )}
    </Banner>
  )
}

// ---------- 查看态节点 ----------

function TreeNode({
  numbered,
  depth,
  defaultOpen,
  onTrace,
}: {
  /** 编号装饰树节点（prefix=编号前缀，none/封面为空串不渲染） */
  numbered: NumberedNode
  depth: number
  /** 搜索过滤模式：只保留命中路径，全部展开 */
  defaultOpen?: boolean
  /** 来源徽章点击 → 追溯弹窗 */
  onTrace?: (id: string) => void
}) {
  // 深层默认折叠，避免长目录一次性铺满；children 键可能缺失（存储内容不物化默认值）
  const [open, setOpen] = useState(defaultOpen ?? depth < 1)
  const node = numbered.node
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
              {numbered.prefix && (
                <span className="mr-0.5 text-muted-foreground">{numbered.prefix}</span>
              )}
              {node.目录名称}
            </span>
            {(node.来源位置 ?? []).map((id) => {
              const meaning = BADGE_LABELS[id.split('-')[0] ?? '']
              const tip = meaning
                ? `${id} ${meaning} · 点击看原文与出处`
                : `查看 ${id} 的登记原文与出处`
              return onTrace ? (
                <button
                  key={id}
                  type="button"
                  style={badgeStyle(id)}
                  onClick={() => onTrace(id)}
                  title={tip}
                  className="cursor-pointer rounded px-1.5 py-px text-[10px] font-medium hover:brightness-95"
                >
                  {id}
                </button>
              ) : (
                <span key={id} style={badgeStyle(id)} title={tip} className="rounded px-1.5 py-px text-[10px] font-medium">
                  {id}
                </span>
              )
            })}
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
          {numbered.children.map((child, i) => (
            <TreeNode
              key={defaultOpen ? `q-${i}` : i}
              numbered={child}
              depth={depth + 1}
              defaultOpen={defaultOpen}
              onTrace={onTrace}
            />
          ))}
        </div>
      )}
    </div>
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
        tone === 'warn' && 'border-warning/50 bg-warning/10 text-warning',
      )}
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span className="flex-1 text-ink-2">{children}</span>
      {action}
    </div>
  )
}

function RegistrySection({
  entries,
}: {
  entries: [string, { type?: string; text?: string; 出处?: string }][]
}) {
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
              <span style={badgeStyle(id)} className='shrink-0 rounded px-1.5 py-px font-medium'>{id}</span>
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
