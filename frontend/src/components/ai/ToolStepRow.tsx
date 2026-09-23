import { memo, useState } from 'react'
import type { ToolStep } from '@/api/sse'
import { Brain, ChevronDown } from 'lucide-react'
import { MemoMarkdown } from '@/components/ai/MemoMarkdown'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { SKILL_LOAD_LABEL, formatStepResult, stepArgLabel, toolDisplayName, toolIcon } from '@/components/ai/toolDisplay'
import { useAutoCollapse } from '@/hooks/useAutoCollapse'
import { humanizeError } from '@/lib/errorText'
import { mdRemarkPlugins } from '@/lib/markdown'
import { cn } from '@/lib/utils'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import ReactMarkdown from 'react-markdown'

/** 步骤思考折叠行：该工具调用前模型的一段思考（tool.called 封段写入 step.reasoning，
 *  与旁白封段同一条规则）。默认收起、点开看全文（定高滚动）——思考是辅助材料，
 *  流水结构（思考→工具→结果→思考）靠行序呈现。旧 trace 快照无此键，防御性跳过。
 *  memo：静态内容，流式期间父级重渲染不重解析 markdown。 */
export const StepThinking = memo(function StepThinking({ text }: { text?: string }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <Collapsible className="group cv-step" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-1.5 py-0.5 text-left text-[13px] text-muted-foreground/80 transition-colors hover:text-foreground">
        <Brain className="size-3.5 shrink-0" aria-hidden />
        <span className="whitespace-nowrap">思考</span>
        <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden">
        <div className="border-line border-l-2 py-0.5 pl-3 pr-2">
          <div className="max-h-72 overflow-y-auto pr-1 text-[13px] leading-relaxed text-muted-foreground">
            <MemoMarkdown text={text} />
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
})

/** 步骤前旁白行：该工具调用前模型输出的一句过程说明（tool.called 封段写入 step.text）。
 *  旧 trace 快照无此键，防御性跳过。正文样式（深色正文号，同参考产品的流内叙述段），
 *  按 markdown 渲染（旁白里的 **加粗** 不再裸露）。暂停消息的正文也经此渲染进过程卡。
 *  memo：流式期间（纯正文 token）父级重渲染不重解析旁白 markdown。 */
export const NarrationLine = memo(function NarrationLine({ text }: { text?: string }) {
  if (!text) return null
  return (
    <div className="py-1 text-[15px] leading-relaxed text-foreground">
      <ReactMarkdown remarkPlugins={mdRemarkPlugins}>{text}</ReactMarkdown>
    </div>
  )
})

/** 普通工具步骤行：标题只显示「工具名 · 状态」（不展示业务内容，执行中整段微光），
 *  完成后自动收缩（用户手动展开不被覆盖）。点击展开详情 = 关键参数（路径/问题等）+ 结果摘要/错误。
 *  技能文件读取（read_file 指向 skills/）标题/图标/参数经 toolDisplay 换成语义化文案。
 *  embedded=嵌入折叠组内渲染：组首步骤的旁白/思考已上提组头常驻，跳过防重复，
 *  字号也随组降到 12px（子代理卡内的嵌套场景）。
 *  memo：步骤是不可变快照（appendReasoning/fillStep 保留未命中引用），子代理思考
 *  流式期间未受影响的行跳过重渲染。 */
export const ToolStepRow = memo(function ToolStepRow({
  step,
  embedded,
}: {
  step: ToolStep
  embedded?: boolean
}) {
  const [open, setOpen] = useAutoCollapse(step.status)
  const arg = stepArgLabel(step.tool, step.args)
  const Icon = toolIcon(step.tool, step.args)
  const statusText =
    step.status === 'running'
      ? '执行中'
      : step.status === 'error'
        ? '失败'
        : step.status === 'paused'
          ? '已暂停'
          : '已完成'
  return (
    <Collapsible className="group cv-step" open={open} onOpenChange={setOpen}>
      {!embedded && (
        <>
          <StepThinking text={step.reasoning} />
          <NarrationLine text={step.text} />
        </>
      )}
      <CollapsibleTrigger
        className={cn(
          'flex w-full cursor-pointer items-center gap-1.5 py-0.5 text-left text-muted-foreground transition-colors hover:text-foreground',
          embedded ? 'text-[12px]' : 'text-[13px]',
        )}
      >
        <Icon className="size-3.5 shrink-0" aria-hidden />
        {step.status === 'running' ? (
          <TextShimmer className="whitespace-nowrap">
            {toolDisplayName(step.tool, step.args)} · {statusText}
          </TextShimmer>
        ) : (
          <>
            <span className="whitespace-nowrap">{toolDisplayName(step.tool, step.args)}</span>
            <span className="whitespace-nowrap">· {statusText}</span>
          </>
        )}
        <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden">
        {/* 左竖线对齐深度思考块（border-l-2 + pl-3 = 14px，与原 pl-3.5 缩进等宽，文字不动） */}
        <div className="border-line border-l-2 py-0.5 pl-3 pr-2">
          {arg && (
            <div className="break-all font-mono text-xs text-muted-foreground/80">{arg}</div>
          )}
          {step.status === 'error' && step.error ? (
            // 首屏人话 + 原始错误详情（内部路径/SDK 细节不进首行）；长输出定高滚动
            <div className="max-h-72 overflow-y-auto pr-1">
              <p className="art-result" style={{ color: 'var(--Color-danger)' }}>
                {humanizeError(step.error)}
              </p>
              <p className="art-result break-all text-xs text-muted-foreground/70">{step.error}</p>
            </div>
          ) : step.summary ? (
            <div className="art-result max-h-72 overflow-y-auto pr-1">
              {formatStepResult(step.tool, step.summary)}
            </div>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
})

/** 折叠组 steps 数组的等价判定：分段每轮重建数组，按元素引用比较
 *  （步骤是不可变快照，引用相等即内容相等）。 */
export const sameSteps = (a: ToolStep[], b: ToolStep[]) =>
  a.length === b.length && a.every((s, i) => s === b[i])

/** 技能加载折叠组：技能正文由模型 read_file 读入，事件层无专用工具名——语义是
 *  「加载技能」而非「读取文件」（判据见 toolDisplay.skillFileInfo）：连续 N 次技能
 *  读取收成一行「加载技能 ×N」，技能 chips 折叠态常驻（这次读进来哪些技能/参考文档
 *  一眼可见，不埋进展开区）；展开后逐个渲染步骤行，参数与结果原样可审计。组首步骤的
 *  旁白/思考上提组头常驻（封段规则：同轮只有首个携带），活跑时计数随 tool.called
 *  逐个增长、chips 逐个出现。主线程与子代理卡内共用（embedded 降一档字号）。
 *  memo 比较器按元素引用（同 AskedQuestions/GrepBatch）。 */
export const SkillBatch = memo(
  function SkillBatch({ steps, embedded }: { steps: ToolStep[]; embedded?: boolean }) {
    const [open, setOpen] = useState(false)
    const first = steps[0]
    const errors = steps.filter((s) => s.status === 'error').length
    const running = steps.some((s) => s.status === 'running')
    // 图标取组内首个步骤（技能读取 → BookOpen），与步骤行的图标选择单源
    const Icon = toolIcon('read_file', first.args)
    return (
      <div className="cv-step">
        <StepThinking text={first.reasoning} />
        <NarrationLine text={first.text} />
        <Collapsible className="group" open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger
            className={cn(
              'flex w-full cursor-pointer items-center gap-1.5 py-0.5 text-left text-muted-foreground transition-colors hover:text-foreground',
              embedded ? 'text-[12px]' : 'text-[13px]',
            )}
          >
            <Icon className="size-3.5 shrink-0" aria-hidden />
            {running ? (
              <TextShimmer className="whitespace-nowrap">
                {SKILL_LOAD_LABEL} ×{steps.length}
              </TextShimmer>
            ) : (
              <span className="whitespace-nowrap">
                {SKILL_LOAD_LABEL} ×{steps.length}
                {errors > 0 ? ` · ${errors} 失败` : ''}
              </span>
            )}
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          {/* 技能 chips：折叠态常驻，读取失败置灰 */}
          <div className="flex flex-wrap gap-x-2 gap-y-0.5 py-0.5 pl-5 text-[11px] leading-5">
            {steps.map((s) => (
              <span
                key={s.id ?? s.toolCallId}
                className={cn(
                  'whitespace-nowrap',
                  s.status === 'error' ? 'text-muted-foreground/40' : 'text-foreground',
                )}
              >
                {stepArgLabel('read_file', s.args)}
              </span>
            ))}
          </div>
          <CollapsibleContent className="overflow-hidden">
            <div className="border-line space-y-0.5 border-l-2 py-0.5 pl-3 pr-2">
              {steps.map((s, i) => (
                <ToolStepRow key={s.id ?? s.toolCallId ?? i} step={s} embedded />
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    )
  },
  (prev, next) => sameSteps(prev.steps, next.steps) && prev.embedded === next.embedded,
)
