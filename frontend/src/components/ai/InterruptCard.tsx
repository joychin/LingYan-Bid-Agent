import { useState } from 'react'
import { ArrowLeft, ArrowRight, Check, MessageCircleQuestion, ShieldQuestion, X } from 'lucide-react'
import type { HitlDecision } from '@/api/client'
import type { InterruptRequest } from '@/api/sse'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { toolDisplayName } from '@/components/ai/toolDisplay'

/** respond-only（ask_human 问答型）：只允许 respond。 */
export function isQuestion(req: InterruptRequest): boolean {
  const allowed = req.allowed
  return !!allowed && allowed.length > 0 && allowed.every((d) => d === 'respond')
}

/** 含问答的快照走向导 UI（单问 = N=1 特例：无序号/进度，其余同构）；
 *  纯审批快照走批量批准/拒绝卡。 */
export function hasQuestion(requests: InterruptRequest[]): boolean {
  return requests.some(isQuestion)
}

/** 每步草稿：question 步用 picked/text（text=卡内补充输入框），approval 步用 approval/reason。 */
export interface StepDraft {
  picked: string[]
  text: string
  approval?: 'approve' | 'reject'
  reason?: string
}

/** 当前步是否已答（question：点选或补充文字至少其一；approval：已选择）。 */
export function stepAnswered(req: InterruptRequest, draft: StepDraft): boolean {
  return isQuestion(req)
    ? draft.picked.length > 0 || draft.text.trim() !== ''
    : draft.approval !== undefined
}

function previewArgs(args: Record<string, unknown>): string {
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
}

/** options 字符串（「；」/「;」分隔）→ 去空候选项列表。 */
function parseOptions(raw: unknown): string[] {
  if (typeof raw !== 'string') return []
  return raw
    .split(/[；;]/)
    .map((o) => o.trim())
    .filter(Boolean)
}

/** 候选项尾部「（推荐）」标记 → 渲染时剥离为主文本 + 角标；点选/回传仍用原字符串。 */
function parseRecommendation(opt: string): { label: string; recommended: boolean } {
  const m = opt.match(/^(.*?)\s*[（(]推荐[）)]$/)
  if (!m) return { label: opt, recommended: false }
  return { label: m[1].trim(), recommended: true }
}

/** question 首个换行前=主问题，其后=「为什么问」副标题（弱化色小字）。 */
function splitQuestion(raw: string): { main: string; sub: string } {
  const idx = raw.indexOf('\n')
  if (idx < 0) return { main: raw, sub: '' }
  return { main: raw.slice(0, idx).trim(), sub: raw.slice(idx + 1).trim() }
}

/** question 主问题 + 副标题（ask_human 两段式写法：首行问题 + 换行 + 影响说明）。 */
function QuestionMain({ q }: { q: InterruptRequest }) {
  const raw = String(q.args?.question ?? q.description ?? '（未提供问题内容）')
  const { main, sub } = splitQuestion(raw)
  return (
    <>
      <div className="mt-1.5 whitespace-pre-wrap text-ink">{main}</div>
      {sub && (
        <div className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{sub}</div>
      )}
    </>
  )
}

function RecommendBadge() {
  return (
    <span className="ml-1 rounded border border-ink-3/50 px-1 py-px text-[10px] leading-none text-ink-2">
      推荐
    </span>
  )
}

/** 单选圆点（选中实心）或多选方框（选中打勾）。选中态走中性灰（ink 系），
 *  与会话列表等 Workspace 组件的选中语言一致（用户拍板：选中态偏好中性灰非品牌蓝）。 */
function OptionControl({ selected, multiple }: { selected: boolean; multiple: boolean }) {
  if (multiple) {
    return (
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
          selected ? 'border-ink bg-ink text-background' : 'border-line-2 bg-background'
        }`}
      >
        {selected && <Check className="h-3 w-3" />}
      </span>
    )
  }
  return (
    <span
      className={`h-4 w-4 shrink-0 rounded-full border-2 ${
        selected ? 'border-ink bg-ink' : 'border-line-2 bg-background'
      }`}
    />
  )
}

/**
 * 垂直整行选项列表（参考 Codex ask-for-question 形态）：单/多选控件 + 整行高亮 +
 * 「（推荐）」尾标渲染为角标；点选/回传仍用原字符串。
 */
function OptionList({
  options,
  selected,
  multiple,
  selectable,
  disabled,
  onToggle,
}: {
  options: string[]
  selected: string[]
  multiple: boolean
  selectable: boolean
  disabled: boolean
  onToggle: (opt: string) => void
}) {
  if (options.length === 0) return null
  return (
    <div className="mt-2 flex flex-col gap-1.5">
      {options.map((opt) => {
        const { label, recommended } = parseRecommendation(opt)
        const isSelected = selected.includes(opt)
        const cls = isSelected
          ? 'border-ink-3 bg-secondary'
          : 'border-line bg-background hover:border-line-2'
        const inner = (
          <>
            <OptionControl selected={isSelected} multiple={multiple} />
            <span className="min-w-0 flex-1 text-[13px] leading-snug text-ink">{label}</span>
            {recommended && <RecommendBadge />}
          </>
        )
        if (!selectable || disabled) {
          return (
            <div
              key={opt}
              className={`flex w-full items-center gap-2.5 rounded-md border px-2.5 py-2 ${cls}`}
            >
              {inner}
            </div>
          )
        }
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onToggle(opt)}
            aria-pressed={isSelected}
            title={multiple ? '多选：可点选多个' : '单选'}
            className={`flex w-full items-center gap-2.5 rounded-md border px-2.5 py-2 text-left transition-colors ${cls}`}
          >
            {inner}
          </button>
        )
      })}
    </div>
  )
}

/** 审批项明细：工具名 + 描述 + 参数折叠（批量卡与向导审批步共用）。 */
function ApprovalDetail({ req }: { req: InterruptRequest }) {
  return (
    <div className="rounded-md border border-line bg-background px-2 py-1.5">
      <div className="text-[12px] font-medium text-ink">{toolDisplayName(req.tool)}</div>
      {req.description && <div className="mt-0.5 text-xs text-ink-2">{req.description}</div>}
      {Object.keys(req.args ?? {}).length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer select-none text-xs text-muted-foreground hover:text-foreground">
            查看参数
          </summary>
          <pre className="mt-1 max-h-40 overflow-auto rounded bg-muted px-2 py-1.5 font-mono text-[11px] leading-relaxed text-ink-2">
            {previewArgs(req.args)}
          </pre>
        </details>
      )}
    </div>
  )
}

/** 向导态注入（hasQuestion 为 true 时 ChatView 必传）。 */
export interface WizardProps {
  stepIndex: number
  stepDrafts: StepDraft[]
  /** 当前步选项点选（question 步） */
  onToggleStep: (opt: string) => void
  /** 当前步补充文字输入（question 步卡内输入框） */
  onTextChange: (v: string) => void
  /** 当前步审批选择（approval 步，radio 语义） */
  onApprovalChoice: (choice: 'approve' | 'reject') => void
  /** 拒绝理由输入（approval 步） */
  onReasonChange: (v: string) => void
  /** -1=上一项；+1=下一项/最后一项提交全部（未答守卫在宿主） */
  onNav: (dir: -1 | 1) => void
}

/**
 * HITL 待裁决卡（run.interrupt 后渲染）。两种形态：
 * 含问答（单问=向导 N=1 特例）→ 逐项卡内作答（点选+补充输入框+提交）；
 * 纯审批 → 批量批准/拒绝卡。resume 协议要求 decisions 与快照逐位等长，
 * 故多问只能前端逐题收集、最后一项一次提交。
 */
export function InterruptCard({
  requests,
  onDecide = () => {},
  disabled = false,
  wizard,
}: {
  requests: InterruptRequest[]
  /** 审批决策回调（纯审批形态）；向导形态由 onNav 统一提交，不使用 */
  onDecide?: (decisions: HitlDecision[]) => void
  disabled?: boolean
  /** 含问答形态（单问/多问向导统一走这里） */
  wizard?: WizardProps
}) {
  // hooks 必须在早返回之前调用（wizard 分支不使用 reason，仅保 hook 顺序稳定）
  const [reason, setReason] = useState('')
  if (wizard) return <WizardCard requests={requests} disabled={disabled} {...wizard} />

  return (
    <div className="w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
        <ShieldQuestion className="h-3.5 w-3.5" />
        助手请求执行以下操作，等待你的确认
      </div>
      <div className="mt-2 space-y-2">
        {requests.map((r, i) => (
          <ApprovalDetail key={`a-${i}`} req={r} />
        ))}
      </div>
      <input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="拒绝理由（可选，会反馈给助手）"
        className="mt-2 w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none placeholder:text-muted-foreground focus:border-line-2"
      />
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onDecide(requests.map(() => ({ type: 'reject', ...(reason.trim() ? { message: reason.trim() } : {}) })))}
          className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 hover:border-line-2 hover:text-foreground disabled:opacity-50"
        >
          <X className="h-3.5 w-3.5" />
          拒绝
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => onDecide(requests.map(() => ({ type: 'approve' })))}
          className="inline-flex items-center gap-1 rounded-md bg-inverse px-2.5 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          <Check className="h-3.5 w-3.5" />
          批准
        </button>
      </div>
    </div>
  )
}

/**
 * 含问答逐项卡（参考 Codex ask-for-question：一次一项 + N>1 时序号/进度 +
 * 卡内补充输入框 + 提交按钮）。补充/回答全部在卡内完成，主输入框等待期间禁用。
 */
function WizardCard({
  requests,
  disabled,
  stepIndex,
  stepDrafts,
  onToggleStep,
  onTextChange,
  onApprovalChoice,
  onReasonChange,
  onNav,
}: WizardProps & { requests: InterruptRequest[]; disabled: boolean }) {
  const total = requests.length
  const idx = Math.min(stepIndex, total - 1)
  const req = requests[idx]
  const draft: StepDraft = stepDrafts[idx] ?? { picked: [], text: '' }
  const question = isQuestion(req)
  const options = parseOptions(req.args?.options)
  const multiple = Boolean(req.args?.multiple)
  const answered = stepAnswered(req, draft)
  const last = idx + 1 >= total
  const showProgress = total > 1

  return (
    <div className="w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm">
      <div className="flex items-center justify-between text-[12px] font-medium text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          {question ? (
            <MessageCircleQuestion className="h-3.5 w-3.5" />
          ) : (
            <ShieldQuestion className="h-3.5 w-3.5" />
          )}
          {/* 问句项按 tool_use 呈现（同过程步骤的「向你提问」行同族），不像确认弹窗 */}
          {question ? `已询问 ${total} 个问题` : '需要你的确认'}
        </span>
        {showProgress && <span>第 {idx + 1} / {total} 项</span>}
      </div>
      {question && (
        <div className="mt-1 text-[12px] text-muted-foreground">
          <TextShimmer>等待你的回答…</TextShimmer>
        </div>
      )}
      {/* 进度线：已完成项数占比（当前项进行中不计入）；中性灰填充 */}
      {showProgress && (
        <div className="mt-1.5 h-0.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full bg-ink-2 transition-all"
            style={{ width: `${(idx / total) * 100}%` }}
          />
        </div>
      )}

      {question ? (
        <div className="mt-2.5">
          <QuestionMain q={req} />
          <OptionList
            options={options}
            selected={draft.picked}
            multiple={multiple}
            selectable={!disabled}
            disabled={disabled}
            onToggle={onToggleStep}
          />
          {/* 卡内补充输入框：点选与补充同卡完成；Enter=下一项/提交（守卫在宿主 toast） */}
          <input
            value={draft.text}
            onChange={(e) => onTextChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                onNav(1)
              }
            }}
            disabled={disabled}
            placeholder={options.length > 0 ? '补充说明（可选）…' : '输入你的回答…'}
            className="mt-2 w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-[13px] text-ink outline-none placeholder:text-muted-foreground focus:border-line-2 disabled:opacity-50"
          />
        </div>
      ) : (
        <div className="mt-2.5">
          <div className="flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground">
            <ShieldQuestion className="h-3.5 w-3.5" />
            助手请求执行以下操作
          </div>
          <div className="mt-2">
            <ApprovalDetail req={req} />
          </div>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={disabled}
              onClick={() => onApprovalChoice('approve')}
              aria-pressed={draft.approval === 'approve'}
              className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                draft.approval === 'approve'
                  ? 'border-ink-3 bg-secondary text-foreground'
                  : 'border-line bg-background text-ink-2 hover:border-line-2'
              }`}
            >
              <Check className="h-3.5 w-3.5" />
              批准
            </button>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onApprovalChoice('reject')}
              aria-pressed={draft.approval === 'reject'}
              className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                draft.approval === 'reject'
                  ? 'border-error/60 bg-error/5 text-error'
                  : 'border-line bg-background text-ink-2 hover:border-line-2'
              }`}
            >
              <X className="h-3.5 w-3.5" />
              拒绝
            </button>
          </div>
          {draft.approval === 'reject' && (
            <input
              value={draft.reason ?? ''}
              onChange={(e) => onReasonChange(e.target.value)}
              placeholder="拒绝理由（可选，会反馈给助手）"
              className="mt-2 w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs outline-none placeholder:text-muted-foreground focus:border-line-2"
            />
          )}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between">
        {idx > 0 ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onNav(-1)}
            className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1.5 text-xs font-medium text-ink-2 hover:border-line-2 hover:text-foreground disabled:opacity-50"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            上一项
          </button>
        ) : (
          <span />
        )}
        <button
          type="button"
          disabled={disabled || !answered}
          onClick={() => onNav(1)}
          className="inline-flex items-center gap-1 rounded-md bg-inverse px-2.5 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {last ? (showProgress ? '提交全部' : '提交') : '下一项'}
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}
