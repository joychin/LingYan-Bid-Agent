/**
 * 知识库共享小件：状态点、状态文案、徽章（类型/确认/时效）、右区大空态。
 * 列表行与详情头部共用，保证两处状态口径一致。
 */
import { Check, FileText, FolderOpen, Loader2, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import type { KbItem } from '@/api/client'
import { cn } from '@/lib/utils'

/** 是否解析/整理进行中。 */
export function isBusy(item: KbItem): boolean {
  return (
    item.parse_status === 'pending' ||
    item.parse_status === 'parsing' ||
    item.extract_status === 'running'
  )
}

/** 状态点：解析/整理中转圈 / 待确认橙 / 已确认绿 / 失败红。 */
export function StatusDot({ item }: { item: KbItem }) {
  if (isBusy(item)) return <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
  if (item.parse_status === 'failed') return <span className="kb-dot kb-dot--error" title={item.error ?? ''} />
  if (item.review_status === 'pending_review') return <span className="kb-dot kb-dot--warn" title="待确认" />
  return <span className="kb-dot kb-dot--ok" title="已确认" />
}

/** 状态行文案：进行中进度 / 失败 / 类型名。 */
export function statusText(item: KbItem): string {
  if (item.parse_status === 'pending' || item.parse_status === 'parsing')
    return item.progress ?? '解析中…'
  if (item.extract_status === 'running') return item.progress ?? '整理中…'
  if (item.parse_status === 'failed') return '解析失败'
  return item.doc_type_name
}

/** 语义徽章：kind 决定 tint（color-mix 派生，暗色自动跟随）。 */
export function KbBadge({
  kind,
  children,
  title,
}: {
  kind: 'brand' | 'success' | 'warning' | 'danger' | 'neutral'
  children: ReactNode
  title?: string
}) {
  return (
    <span className={cn('kb-badge', `kb-badge--${kind}`)} title={title}>
      {children}
    </span>
  )
}

/** 识别来源徽章的档位警示集合（沿用旧 ParseMetaBar 口径）。 */
export const WARN_CONVERSIONS = new Set([
  'docx-numbered',
  'pdf-numbered',
  'pdf-plain',
  'pdf-fontsize',
  'vision-unavailable',
])

/** 投标常用材料清单（冷启动引导）：写标书时 AI 引用的就是这些——照单备料比
 *  想到什么传什么命中率高得多。纯静态提示，不做上传状态跟踪。 */
const KB_STARTER_LIST = [
  '营业执照',
  '资质 / 体系证书',
  '近三年合同 / 业绩案例',
  '人员证书（建造师、职称等）',
  '财务 / 审计报告',
  '社保缴纳证明',
  '公司介绍',
]

/** 右区大空态（审计 P1：原先只有两行灰字，无动作）。 */
export function KbHeroEmpty({
  onUpload,
  onGoLibrary,
}: {
  onUpload: () => void
  onGoLibrary?: () => void
}) {
  return (
    <div className="kb-hero">
      <span className="kb-hero-ico">
        <FolderOpen className="h-6 w-6" />
      </span>
      <p className="kb-hero-title">知识库还没有资料</p>
      <p className="kb-hero-sub">
        写标书时 AI 引用的「我们有什么、做过什么」全部来自这里——先照下面的清单把常用材料传齐
      </p>
      <ul className="kb-hero-checklist">
        {KB_STARTER_LIST.map((item) => (
          <li key={item}>
            <Check className="h-3 w-3 shrink-0" />
            {item}
          </li>
        ))}
      </ul>
      <button type="button" className="kb-hero-btn" onClick={onUpload}>
        <FileText className="h-4 w-4" />
        上传资料
      </button>
      <p className="kb-hero-alt">
        历史标书 / 范文（.docx）挑章节建素材？
        {onGoLibrary ? (
          <button type="button" className="kb-hero-link" onClick={onGoLibrary}>
            去写作素材库
          </button>
        ) : (
          <span>去写作素材库</span>
        )}
      </p>
    </div>
  )
}

/** 小警示行（解析警告等）。 */
export function WarnLine({ children }: { children: ReactNode }) {
  return (
    <div className="kb-meta-warn">
      <TriangleAlert className="h-3 w-3 shrink-0" />
      <span>{children}</span>
    </div>
  )
}
