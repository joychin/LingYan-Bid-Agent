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

import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileText,
  History,
} from 'lucide-react'
import type { ProcessorProps } from '@/artifacts/registry'
import { getArtifactContent, getArtifactMeta, listWorkbench, restoreArtifact, updateArtifactContent } from '@/api/client'
import { cn } from '@/lib/utils'
import { useToast } from '@/context/Toast'
import { useAutoSave } from '@/hooks/useAutoSave'
import { SaveStateBar } from '@/components/editors/SaveStateBar'
import { SourceTraceDialog } from '@/components/processors/SourceTraceDialog'
import { DirectoryEditor } from '@/components/processors/DirectoryEditor'
import { structureSignature, type DirectoryData, type EditNode } from '@/components/processors/directoryTree'

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

export function DirectoryProcessor({ artifact, content, onOpenWorkbench }: ProcessorProps) {
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
  docsRef.current = docs

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

  /** 来源追溯「查看原文上下文」：出处锚点（章节名（L412-L430，第23页））的行号
   *  指向招标文件解析 md（parse/ 下首个 .md——单主文件场景；多补充文件时用户
   *  在面板自行切换），打开工作台只读定位视图。 */
  const openSourceContext = async (_id: string, entry: { 出处?: string }) => {
    if (!onOpenWorkbench || !artifact.task_id) return
    const m = entry.出处?.match(/L(\d+)/)
    const line = m ? Number(m[1]) : undefined
    try {
      const { files } = await listWorkbench(artifact.task_id)
      const parseFile = files.find((f) => f.path.startsWith('parse/'))
      if (!parseFile) {
        toast('未找到已解析的原文（work/parse/ 为空）', 'error')
        return
      }
      setTraceId(null)
      onOpenWorkbench(parseFile.path, line)
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
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
        </div>
      )}
      {editing && structConfirm && (
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

      {editing && docs && (
        <DirectoryEditor
          docs={docs}
          mutate={mutate}
          setDocs={(d) => setDocs(d)}
          markDirty={auto.markDirty}
        />
      )}

      {!editing &&
        renderDocs.map((doc, idx) => (
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
              {(doc.directory ?? []).map((node, i) => (
                <TreeNode
                  key={filtering ? `q-${i}` : i}
                  node={node}
                  depth={0}
                  defaultOpen={filtering}
                  onTrace={setTraceId}
                />
              ))}
            </div>
          </section>
        ))}

      {registryEntries.length > 0 && <RegistrySection entries={registryEntries} />}

      <SourceTraceDialog
        traceId={traceId}
        entry={traceId ? (data.registry ?? {})[traceId] : undefined}
        onClose={() => setTraceId(null)}
        onOpenSource={onOpenWorkbench ? openSourceContext : undefined}
      />
    </div>
  )
}

// ---------- 查看态节点 ----------

function TreeNode({
  node,
  depth,
  defaultOpen,
  onTrace,
}: {
  node: EditNode
  depth: number
  /** 搜索过滤模式：只保留命中路径，全部展开 */
  defaultOpen?: boolean
  /** 来源徽章点击 → 追溯弹窗 */
  onTrace?: (id: string) => void
}) {
  // 深层默认折叠，避免长目录一次性铺满；children 键可能缺失（存储内容不物化默认值）
  const [open, setOpen] = useState(defaultOpen ?? depth < 1)
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
            {(node.来源位置 ?? []).map((id) =>
              onTrace ? (
                <button
                  key={id}
                  type="button"
                  style={badgeStyle(id)}
                  onClick={() => onTrace(id)}
                  title={`查看 ${id} 的登记原文与出处`}
                  className="cursor-pointer rounded px-1.5 py-px text-[10px] font-medium hover:brightness-95"
                >
                  {id}
                </button>
              ) : (
                <span key={id} style={badgeStyle(id)} className="rounded px-1.5 py-px text-[10px] font-medium">
                  {id}
                </span>
              ),
            )}
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
            <TreeNode
              key={defaultOpen ? `q-${i}` : i}
              node={child}
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
