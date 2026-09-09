/**
 * 资料档案卡（内容页顶部常驻，2026-09-08 重设计新增）：AI 整理出的
 * 内容说明 + 锚点字段（逐字段带程序核对结果）+ 可回答的检索问题，
 * 打开即见，不必翻「信息」tab。编辑仍走信息 tab（「去核对」入口）。
 * 数据 = business（确认版）优先、否则 suggested（建议版）——与检索侧同序。
 */
import { BookText, Check, TriangleAlert } from 'lucide-react'
import type { KbItem, KbTypePayload } from '@/api/client'
import { useKbTypes } from '@/hooks/useKnowledge'
import { cn } from '@/lib/utils'
import { initValues } from './kbDiff'
import { KbBadge } from './kbShared'

export function ArchiveCard({
  item,
  types,
  onEditInfo,
}: {
  item: KbItem
  types: KbTypePayload[]
  onEditInfo: () => void
}) {
  const { data: typeInfo } = useKbTypes()
  const labels = typeInfo?.field_labels ?? {}
  const basis = item.business ?? item.suggested
  if (!basis) return null

  const statement = basis.statement?.trim()
  const questions = (basis.questions ?? []).filter((q) => q.trim())
  const values = initValues(basis)
  const typeDef = types.find((t) => t.code === (basis.doc_type ?? item.doc_type))
  const fieldKeys = [
    ...new Set([...(typeDef?.time_fields ?? []), 'project_name', 'client', ...Object.keys(values)]),
  ].filter((k) => (values[k] ?? '').trim())
  const sources = basis.fields ?? {}
  if (!statement && fieldKeys.length === 0 && questions.length === 0) return null

  // 核对结果逐字段呈现：只对「机器仍守 suggested」的条目显示（人工确认过=人已拍板）
  const checkVisible = !item.business || item.business.confirmed_by === 'auto'
  const checkByField = new Map((item.check_result?.results ?? []).map((r) => [r.field, r]))

  return (
    <div className="kb-archive">
      <div className="kb-archive-head">
        <BookText className="h-3.5 w-3.5 shrink-0" />
        <span className="kb-archive-title">资料档案</span>
        {item.business ? (
          <KbBadge
            kind="success"
            title={item.business.confirmed_by === 'auto' ? '程序核对通过后自动确认' : undefined}
          >
            {item.business.confirmed_by === 'auto' ? '已确认 · 程序核对' : '已确认'}
          </KbBadge>
        ) : (
          <KbBadge kind="warning">AI 整理 · 数字须回原文核对</KbBadge>
        )}
        <button type="button" className="kb-archive-act" onClick={onEditInfo}>
          {item.review_status === 'pending_review' ? '去核对' : '编辑信息'}
        </button>
      </div>

      {statement && <p className="kb-archive-statement">{statement}</p>}

      {fieldKeys.length > 0 && (
        <div className="kb-fields-grid">
          {fieldKeys.map((k) => {
            const check = checkVisible ? checkByField.get(k) : undefined
            return (
              <div key={k} className="kb-field">
                <span className="kb-field-label">
                  {labels[k] ?? k}
                  {check &&
                    (check.ok ? (
                      <span className="kb-field-ok" title={check.detail}>
                        <Check className="h-3 w-3" />
                      </span>
                    ) : (
                      <span className="kb-field-bad" title={check.detail}>
                        <TriangleAlert className="h-3 w-3" />
                      </span>
                    ))}
                </span>
                <span className="kb-field-value" title={sources[k]?.source ?? undefined}>
                  {values[k]}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {questions.length > 0 && (
        <div className="kb-q-block">
          <span className="kb-q-label">可回答的问题</span>
          <div className="kb-q-pills">
            {questions.map((q, i) => (
              <span key={`${i}-${q}`} className={cn('kb-q-pill')}>
                {q}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
