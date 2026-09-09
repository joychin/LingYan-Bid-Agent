/**
 * 知识库纯逻辑：确认版（business）vs 建议版（suggested）的差异计算、
 * 信息表单初始化、采纳选择 → 保存体的组装。UI 无关，方便直测。
 */
import type { KbItem, KbTypePayload } from '@/api/client'

export type AdoptChoice = 'suggest' | 'keep'
export type AdoptSectionKey = 'questions' | 'statement' | 'fields' | 'docType'

export interface FieldChange {
  key: string
  old: string
  neu: string
}

export interface KbDiff {
  questions: { old: string[]; neu: string[] } | null
  statement: { old: string; neu: string } | null
  fields: FieldChange[] | null
  docType: { old: string; neu: string } | null
}

export function typeNameOf(types: KbTypePayload[], code: string): string {
  return types.find((t) => t.code === code)?.name ?? code
}

export function initQuestions(basis: KbItem['suggested']): string[] {
  return (basis?.questions ?? []).filter((q) => typeof q === 'string' && q.trim())
}

export function initValues(basis: KbItem['suggested']): Record<string, string> {
  const init: Record<string, string> = {}
  for (const [k, v] of Object.entries(basis?.fields ?? {})) init[k] = v?.value ?? ''
  for (const [k, v] of Object.entries(basis?.extra ?? {})) init[k] = v?.value ?? ''
  return init
}

/** 只列「可采纳」的差异：建议侧为空的更新没有采纳价值（采纳即丢数据）。 */
export function computeKbDiff(item: KbItem, types: KbTypePayload[]): KbDiff | null {
  const biz = item.business
  const sug = item.suggested
  if (!biz || !sug) return null
  const out: KbDiff = { questions: null, statement: null, fields: null, docType: null }

  const oldQs = initQuestions(biz)
  const neuQs = initQuestions(sug)
  if (neuQs.length > 0 && neuQs.join('\n') !== oldQs.join('\n')) {
    out.questions = { old: oldQs, neu: neuQs }
  }

  const oldSt = (biz.statement ?? '').trim()
  const neuSt = (sug.statement ?? '').trim()
  if (neuSt && neuSt !== oldSt) out.statement = { old: oldSt, neu: neuSt }

  const a = initValues(biz)
  const b = initValues(sug)
  const changes: FieldChange[] = []
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    const neu = b[k] ?? ''
    if (neu && neu !== (a[k] ?? '')) changes.push({ key: k, old: a[k] ?? '', neu })
  }
  out.fields = changes.length > 0 ? changes : null

  const neuType = sug.doc_type
  if (neuType && neuType !== biz.doc_type && types.some((t) => t.code === neuType)) {
    out.docType = { old: biz.doc_type ?? 'other', neu: neuType }
  }

  return out.questions || out.statement || out.fields || out.docType ? out : null
}

export function diffSummary(diff: KbDiff, types: KbTypePayload[]): string {
  const parts: string[] = []
  if (diff.questions) {
    parts.push(
      diff.questions.old.length === 0
        ? `新增 ${diff.questions.neu.length} 个检索问题`
        : `检索问题有更新（${diff.questions.old.length}→${diff.questions.neu.length} 条）`,
    )
  }
  if (diff.statement) parts.push('内容说明有改动')
  if (diff.fields) parts.push(`${diff.fields.length} 处字段变化`)
  if (diff.docType) parts.push(`类型建议改为「${typeNameOf(types, diff.docType.neu)}」`)
  return parts.join(' · ')
}

export function defaultChoices(diff: KbDiff | null): Record<AdoptSectionKey, AdoptChoice> {
  return {
    // 纯新增（确认版为空）默认采纳——没有可损失的东西；有旧值的一律默认保留，逐区选择
    questions: diff?.questions && diff.questions.old.length === 0 ? 'suggest' : 'keep',
    statement: 'keep',
    fields: 'keep',
    docType: 'keep',
  }
}

export function buildAdoptBody(
  item: KbItem,
  diff: KbDiff,
  choices: Record<AdoptSectionKey, AdoptChoice>,
): {
  doc_type: string
  statement?: string
  questions: string[]
  fields: Record<string, string>
} {
  const biz = item.business!
  const fields: Record<string, string> = {}
  for (const [k, v] of Object.entries(initValues(biz))) {
    if (v.trim()) fields[k] = v
  }
  if (choices.fields === 'suggest') {
    for (const f of diff.fields ?? []) fields[f.key] = f.neu
  }
  const statement =
    choices.statement === 'suggest' && diff.statement ? diff.statement.neu : (biz.statement ?? '')
  const questions =
    choices.questions === 'suggest' && diff.questions ? diff.questions.neu : initQuestions(biz)
  return {
    doc_type:
      choices.docType === 'suggest' && diff.docType ? diff.docType.neu : (biz.doc_type ?? 'other'),
    statement: statement.trim() || undefined,
    questions,
    fields,
  }
}
