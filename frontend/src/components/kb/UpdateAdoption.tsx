/**
 * 重新识别后的采纳交互：更新条常驻亮差异，点开对比卡逐区「采纳建议 / 保留我的」，
 * 保存才落确认版——守住「确认内容不被静默覆盖」，但把两边差了什么摆到明面上。
 */
import { useEffect, useState, type ReactNode } from 'react'
import { X, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { KbItem, KbTypePayload } from '@/api/client'
import { useConfirmMetadata, useKbTypes } from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { cn } from '@/lib/utils'
import {
  buildAdoptBody,
  defaultChoices,
  diffSummary,
  typeNameOf,
  type AdoptChoice,
  type AdoptSectionKey,
  type KbDiff,
} from './kbDiff'
import { isBusy } from './kbShared'

export function UpdateAdoption({
  item,
  types,
  diff,
}: {
  item: KbItem
  types: KbTypePayload[]
  diff: KbDiff | null
}) {
  const confirm = useConfirmMetadata()
  const { toast } = useToast()
  const labels = useKbTypes().data?.field_labels ?? {}
  const [dismissedStamp, setDismissedStamp] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [choices, setChoices] = useState<Record<AdoptSectionKey, AdoptChoice>>(() =>
    defaultChoices(diff),
  )
  const busy = isBusy(item)

  // 新一轮识别落地（updated_at 变化）→ 重置选择与展开态
  useEffect(() => {
    setOpen(false)
    setChoices(defaultChoices(diff))
  }, [item.id, item.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps

  if (busy || !diff || dismissedStamp === item.updated_at) return null

  const save = async () => {
    try {
      await confirm.mutateAsync({ id: item.id, body: buildAdoptBody(item, diff, choices) })
      toast('已保存', 'success')
      setOpen(false)
    } catch (e) {
      toast(e instanceof Error ? e.message : '保存失败', 'error')
    }
  }

  if (!open) {
    return (
      <div className="kb-update-bar">
        <Zap className="h-3.5 w-3.5 shrink-0" />
        <span className="kb-update-text">识别已更新：{diffSummary(diff, types)}</span>
        <button type="button" className="kb-update-act" onClick={() => setOpen(true)}>
          对比采纳
        </button>
        <button
          type="button"
          className="kb-update-act kb-update-act--ghost"
          onClick={() => setDismissedStamp(item.updated_at)}
        >
          知道了
        </button>
      </div>
    )
  }

  return (
    <div className="kb-adopt">
      <div className="kb-adopt-head">
        <span>识别更新——逐区选择，保存后生效</span>
        <button
          type="button"
          className="kb-adopt-close"
          title="收起"
          onClick={() => setOpen(false)}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {diff.questions && (
        <AdoptSection
          title="检索问题"
          adoptLabel={`采纳建议（${diff.questions.neu.length} 条）`}
          keepLabel={`保留我的（现为 ${diff.questions.old.length} 条）`}
          choice={choices.questions}
          onChoose={(c) => setChoices((s) => ({ ...s, questions: c }))}
        >
          <div className="kb-adopt-pills">
            {diff.questions.neu.map((q) => (
              <span key={q} className="kb-q-pill">
                {q}
              </span>
            ))}
          </div>
        </AdoptSection>
      )}

      {diff.statement && (
        <AdoptSection
          title="内容说明"
          adoptLabel="采纳新版"
          keepLabel="保留我的"
          choice={choices.statement}
          onChoose={(c) => setChoices((s) => ({ ...s, statement: c }))}
        >
          <div className="kb-adopt-sides">
            <div className="kb-adopt-side">
              <span className="kb-adopt-side-tag">我的</span>
              <p>{diff.statement.old || '（空）'}</p>
            </div>
            <div className="kb-adopt-side kb-adopt-side--new">
              <span className="kb-adopt-side-tag">AI 新版</span>
              <p>{diff.statement.neu}</p>
            </div>
          </div>
        </AdoptSection>
      )}

      {diff.fields && diff.fields.length > 0 && (
        <AdoptSection
          title="锚点字段"
          adoptLabel={`采纳（${diff.fields.length} 处变化）`}
          keepLabel="保留我的"
          choice={choices.fields}
          onChoose={(c) => setChoices((s) => ({ ...s, fields: c }))}
        >
          {diff.fields.map((f) => (
            <div key={f.key} className="kb-adopt-field">
              <span className="kb-adopt-field-label">{labels[f.key] ?? f.key}</span>
              <span className="kb-adopt-field-old">{f.old || '—'}</span>
              <span className="kb-adopt-field-arrow">→</span>
              <span className="kb-adopt-field-new">{f.neu}</span>
            </div>
          ))}
        </AdoptSection>
      )}

      {diff.docType && (
        <AdoptSection
          title="资料类型"
          adoptLabel={`改为「${typeNameOf(types, diff.docType.neu)}」`}
          keepLabel={`保留「${typeNameOf(types, diff.docType.old)}」`}
          choice={choices.docType}
          onChoose={(c) => setChoices((s) => ({ ...s, docType: c }))}
        >
          <div className="kb-adopt-field">
            <span className="kb-adopt-field-label">类型</span>
            <span className="kb-adopt-field-old">{typeNameOf(types, diff.docType.old)}</span>
            <span className="kb-adopt-field-arrow">→</span>
            <span className="kb-adopt-field-new">{typeNameOf(types, diff.docType.neu)}</span>
          </div>
        </AdoptSection>
      )}

      <div className="kb-adopt-foot">
        <Button size="sm" onClick={save} disabled={confirm.isPending}>
          保存修改
        </Button>
      </div>
    </div>
  )
}

function AdoptSection({
  title,
  adoptLabel,
  keepLabel,
  choice,
  onChoose,
  children,
}: {
  title: string
  adoptLabel: string
  keepLabel: string
  choice: AdoptChoice
  onChoose: (c: AdoptChoice) => void
  children?: ReactNode
}) {
  return (
    <div className="kb-adopt-section">
      <div className="kb-adopt-sec-head">
        <span className="kb-adopt-sec-title">{title}</span>
        <div className="kb-adopt-choices">
          <label className={cn('kb-adopt-choice', choice === 'suggest' && 'kb-adopt-choice--on')}>
            <input
              type="radio"
              name={`adopt-${title}`}
              checked={choice === 'suggest'}
              onChange={() => onChoose('suggest')}
            />
            {adoptLabel}
          </label>
          <label className={cn('kb-adopt-choice', choice === 'keep' && 'kb-adopt-choice--on')}>
            <input
              type="radio"
              name={`adopt-${title}`}
              checked={choice === 'keep'}
              onChange={() => onChoose('keep')}
            />
            {keepLabel}
          </label>
        </div>
      </div>
      {children}
    </div>
  )
}
