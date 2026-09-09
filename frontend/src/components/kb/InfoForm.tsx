/**
 * 信息确认表单（2026-09-08 重做）：资料类型（事实/写法分组）+ 内容说明 +
 * 检索问题编辑器（≤10 条、单条 ≤40 字）+ 锚点字段（逐字段带程序核对结果）。
 * 有未保存修改时经 onDirtyChange 上报宿主，切 tab/切条目前宿主弹确认——
 * 探测 + 用户裁决，不加锁。
 */
import { useEffect, useMemo, useState } from 'react'
import { Check, Plus, Trash2, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { KbItem, KbTypePayload } from '@/api/client'
import { useConfirmMetadata, useKbTypes } from '@/hooks/useKnowledge'
import { useToast } from '@/context/Toast'
import { initQuestions, initValues } from './kbDiff'

/** 锚点回文核对汇总条：自动确认=核对全过；人工确认过不再显示（人已拍板）。 */
function AutoCheckBar({ item }: { item: KbItem }) {
  const check = item.check_result
  if (!check || (item.business && item.business.confirmed_by !== 'auto')) return null
  const failed = (check.results ?? []).filter((r) => !r.ok)
  const passed = (check.results ?? []).filter((r) => r.ok)
  if (check.status === 'pass') {
    return (
      <div className="kb-check">
        <span className="kb-check-tag">程序核对通过</span>
        <span className="kb-check-note">
          {passed.length > 0 ? `${passed.map((r) => r.label).join('、')} 均在原文命中` : '本类型无需核对锚点字段'}
        </span>
      </div>
    )
  }
  return (
    <div className="kb-check kb-check--fail">
      {failed.map((r) => (
        <div key={r.field} className="kb-check-row">
          <TriangleAlert className="h-3 w-3 shrink-0" />
          <span>
            {r.label}：{r.detail}
          </span>
        </div>
      ))}
      {passed.length > 0 && (
        <span className="kb-check-note">已在原文命中：{passed.map((r) => r.label).join('、')}</span>
      )}
    </div>
  )
}

function valuesDirty(a: Record<string, string>, b: Record<string, string>): boolean {
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    if ((a[k] ?? '') !== (b[k] ?? '')) return true
  }
  return false
}

export function InfoForm({
  item,
  types,
  onDirtyChange,
}: {
  item: KbItem
  types: KbTypePayload[]
  onDirtyChange: (dirty: boolean) => void
}) {
  const confirm = useConfirmMetadata()
  const { toast } = useToast()
  const labels = useKbTypes().data?.field_labels ?? {}
  const basis = item.business ?? item.suggested
  const [docType, setDocType] = useState<string>(basis?.doc_type ?? item.doc_type ?? 'other')
  const [statement, setStatement] = useState(basis?.statement ?? '')
  const [questions, setQuestions] = useState<string[]>(() => initQuestions(basis))
  const [values, setValues] = useState<Record<string, string>>(() => initValues(basis))
  const initial = useMemo(
    () => ({
      docType: basis?.doc_type ?? item.doc_type ?? 'other',
      statement: basis?.statement ?? '',
      questions: initQuestions(basis),
      values: initValues(basis),
    }),
    [item.id, item.suggested, item.business], // eslint-disable-line react-hooks/exhaustive-deps
  )
  useEffect(() => {
    setDocType(basis?.doc_type ?? item.doc_type ?? 'other')
    setStatement(basis?.statement ?? '')
    setQuestions(initQuestions(basis))
    setValues(initValues(basis))
  }, [item.id, item.suggested, item.business]) // eslint-disable-line react-hooks/exhaustive-deps

  const dirty =
    docType !== initial.docType ||
    statement !== initial.statement ||
    questions.join('\n') !== initial.questions.join('\n') ||
    valuesDirty(values, initial.values)
  useEffect(() => {
    onDirtyChange(dirty)
  }, [dirty]) // eslint-disable-line react-hooks/exhaustive-deps

  const typeDef = types.find((t) => t.code === docType)
  const fieldKeys = [
    ...new Set([...(typeDef?.time_fields ?? []), 'project_name', 'client', ...Object.keys(values)]),
  ]
  const sources = basis?.fields ?? {}
  // 核对结果逐字段呈现：只对「机器仍守 suggested」的条目显示（人工确认过=人已拍板）
  const checkVisible = !item.business || item.business.confirmed_by === 'auto'
  const checkByField = new Map((item.check_result?.results ?? []).map((r) => [r.field, r]))
  const factTypes = types.filter((t) => t.role === 'fact')
  const writingTypes = types.filter((t) => t.role === 'writing')

  const save = async () => {
    try {
      await confirm.mutateAsync({
        id: item.id,
        body: {
          doc_type: docType,
          statement: statement.trim() || undefined,
          questions: questions.map((q) => q.trim()).filter(Boolean),
          fields: values,
        },
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
        <AutoCheckBar item={item} />
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">资料类型</label>
          <select className="kb-select" value={docType} onChange={(e) => setDocType(e.target.value)}>
            <optgroup label="事实资料（证明我们有什么 / 做过什么）">
              {factTypes.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
            </optgroup>
            <optgroup label="写法参考（这类内容怎么写）">
              {writingTypes.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
            </optgroup>
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
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            检索问题（用户怎么问就怎么写；{questions.length}/10 条，单条 ≤40 字）
          </label>
          {questions.map((q, i) => (
            <div key={i} className="kb-q-row">
              <Input
                value={q}
                onChange={(e) => setQuestions((qs) => qs.map((v, j) => (j === i ? e.target.value : v)))}
                placeholder="如：做过哪些医疗行业项目？"
                maxLength={40}
              />
              <button
                type="button"
                className="kb-q-del"
                title="删除该问题"
                onClick={() => setQuestions((qs) => qs.filter((_, j) => j !== i))}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {questions.length < 10 && (
            <button type="button" className="kb-q-add" onClick={() => setQuestions((qs) => [...qs, ''])}>
              <Plus className="h-3.5 w-3.5" />
              添加问题
            </button>
          )}
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">锚点字段（时效与来源标注的依据）</label>
          {fieldKeys.map((k) => {
            const check = checkVisible ? checkByField.get(k) : undefined
            return (
              <div key={k} className="kb-info-field">
                <label className="text-xs font-medium text-muted-foreground">
                  {labels[k] ?? k}
                  {check?.ok && (
                    <span className="kb-field-ok ml-1" title={check.detail}>
                      <Check className="h-3 w-3" />
                    </span>
                  )}
                  {sources[k]?.source && <span className="kb-source">（出处：{sources[k].source}）</span>}
                </label>
                <Input
                  value={values[k] ?? ''}
                  onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                  placeholder="—"
                />
                {check && !check.ok && <p className="kb-field-warnline">{check.detail}</p>}
              </div>
            )
          })}
        </div>
        <div className="flex justify-end">
          <Button size="sm" onClick={save} disabled={confirm.isPending}>
            {item.review_status === 'confirmed' ? '保存修改' : '确认信息'}
          </Button>
        </div>
      </div>
    </div>
  )
}
