import { memo, useMemo, useState } from 'react'
import type { TodoItem, ToolStep } from '@/api/sse'
import { ChevronDown, MessageCircleQuestion } from 'lucide-react'
import { Steps, StepsContent, StepsItem, StepsTrigger } from '@/components/ai/Steps'
import { SubagentCard } from '@/components/ai/SubagentCard'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { stepArgLabel, toolIcon } from '@/components/ai/toolDisplay'
import {
  NarrationLine,
  SkillBatch,
  StepThinking,
  ToolStepRow,
  sameSteps,
} from '@/components/ai/ToolStepRow'
import { segmentToolSteps } from '@/components/ai/traceGroups'
import { stripSelectedPrefix } from '@/lib/hitlMessage'
import { mdRemarkPlugins } from '@/lib/markdown'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import ReactMarkdown from 'react-markdown'

// 步骤行与其构件（StepThinking/NarrationLine/ToolStepRow）已下沉 ToolStepRow.tsx
// （SubagentCard 也要用 SkillBatch，从本文件 import 会与本文件的 SubagentCard 成环）；
// 此处转出，既有消费者（ChatView/ChatMessage）的 import 路径不变。
export { NarrationLine, StepThinking }

/** 已回答的提问折叠组（参考图「已询问 N 个问题」形态）：ask_human 步骤收拢为一组，
 *  每项 = 问题 + 你的回答（结果摘要即用户回答原文）。默认收起——回答过的问题不必
 *  常驻展开，转录里也不再渲染独立的「已选：」回答气泡。
 *  memo 比较器按元素引用（分段每轮重建数组，默认浅比较恒失效）。 */
const AskedQuestions = memo(
  function AskedQuestions({ steps }: { steps: ToolStep[] }) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible className="group" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-1.5 py-0.5 text-left text-[13px] text-muted-foreground transition-colors hover:text-foreground">
        <MessageCircleQuestion className="size-3.5 shrink-0" aria-hidden />
        <span className="whitespace-nowrap">已询问 {steps.length} 个问题</span>
        <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden">
        <div className="border-line space-y-2 border-l-2 py-0.5 pl-3 pr-2">
          {steps.map((s) => (
            <div key={s.id ?? s.toolCallId}>
              <StepThinking text={s.reasoning} />
              <NarrationLine text={s.text} />
              <div className="text-[13px] leading-relaxed text-foreground">
                <ReactMarkdown remarkPlugins={mdRemarkPlugins}>
                  {stepArgLabel('ask_human', s.args) || '（问题详情见参数）'}
                </ReactMarkdown>
              </div>
              {s.summary && (
                <div className="text-xs text-muted-foreground">你的回答：{stripSelectedPrefix(s.summary)}</div>
              )}
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
  },
  (prev, next) => sameSteps(prev.steps, next.steps),
)

/** todos 缺省值（活卡不传——清单上移会话区右上角 TodoPanel，2026-09-12）：
 *  模块级常量而非默认参数内联 []，保 RunTrace memo 浅比较引用稳定。 */
const EMPTY_TODOS: TodoItem[] = []

/** grep 无命中时 deepagents 格式器的固定文案（backends utils format_grep_matches）。
 *  只用于词表 chip 置灰与命中计数，提示非门禁；上游措辞变化最坏退化为标注不准。 */
const GREP_NO_MATCH = 'No matches found'

/** 连续 grep 批次折叠组（废标反查词表场景）：N 行「检索文件」收成一行
 *  「检索 ×N · 命中 H/N」。词表 chips 折叠态常驻可见——哪些词查过、哪些打中
 *  是废标审计关心的事，不埋进展开区；展开后逐个渲染普通步骤行（参数+结果
 *  原样可审计）。组首步骤的旁白/思考上提组头常驻（封段规则：同轮只有首个
 *  调用携带），活跑时计数与 chips 随 tool.called 逐个增长、命中词逐个点亮。
 *  memo 比较器按元素引用（同 AskedQuestions）。 */
const GrepBatch = memo(
  function GrepBatch({ steps }: { steps: ToolStep[] }) {
  const [open, setOpen] = useState(false)
  const first = steps[0]
  const isHit = (s: ToolStep) => s.status === 'done' && !!s.summary && s.summary !== GREP_NO_MATCH
  const hits = steps.filter(isHit).length
  const errors = steps.filter((s) => s.status === 'error').length
  const running = steps.some((s) => s.status === 'running')
  const Icon = toolIcon('grep')
  return (
    <div className="cv-step">
      <StepThinking text={first.reasoning} />
      <NarrationLine text={first.text} />
      <Collapsible className="group" open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-1.5 py-0.5 text-left text-[13px] text-muted-foreground transition-colors hover:text-foreground">
          <Icon className="size-3.5 shrink-0" aria-hidden />
          {running ? (
            <TextShimmer className="whitespace-nowrap">检索 ×{steps.length}</TextShimmer>
          ) : (
            <span className="whitespace-nowrap">
              检索 ×{steps.length} · 命中 {hits}/{steps.length}
              {errors > 0 ? ` · ${errors} 失败` : ''}
            </span>
          )}
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        {/* 词表 chips：折叠态常驻，命中正常色、未命中/进行中置灰 */}
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 py-0.5 pl-5 text-[11px] leading-5">
          {steps.map((s) => (
            <span
              key={s.id ?? s.toolCallId}
              className={cn(
                'whitespace-nowrap',
                isHit(s) ? 'text-foreground' : 'text-muted-foreground/40',
              )}
            >
              {stepArgLabel('grep', s.args)}
            </span>
          ))}
        </div>
        <CollapsibleContent className="overflow-hidden">
          <div className="border-line space-y-0.5 border-l-2 py-0.5 pl-3 pr-2">
            {steps.map((s, i) => (
              <ToolStepRow key={s.id ?? s.toolCallId ?? i} step={s} embedded={i === 0} />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
  },
  (prev, next) => sameSteps(prev.steps, next.steps),
)

/** 技能加载折叠组（技能正文由模型 read_file 读入，事件层无专用工具名——语义是
/** 执行过程流（工具行 + 任务清单）：RunMessage（运行中）与历史消息（trace 快照）共用。
 *  仿参考产品扁平时间线：旁白正文与工具行按序平铺（外层运行头负责折叠）。
 *  task 步骤渲染 SubagentCard（含子代理 children/reasoning），ask_human 步骤收进
 *  问答折叠组，连续 grep 批次收进检索折叠组（分段规则见 traceGroups），其余工具
 *  渲染普通步骤行。任务清单组（todos）仅历史侧传入——活卡的清单在会话区右上角
 *  TodoPanel 常驻浮层（2026-09-12 提取），历史快照仍随过程区归档可见。
 *  memo：流式正文 token 期间 tools/todos 引用不变 → 整个过程区跳过重渲染
 *  （白名单制：新增 prop 必须是引用稳定或值类型，否则比较器要同步改）。 */
export const RunTrace = memo(function RunTrace({
  tools,
  todos = EMPTY_TODOS,
  done = 0,
  total = 0,
}: {
  tools: ToolStep[]
  todos?: TodoItem[]
  done?: number
  total?: number
}) {
  // 分段只在 tools 引用变化时重算（todos/done/total 变化不重跑），行级 memo 再挡掉
  // 未受影响的行（子代理思考流式只换命中的 task 步骤引用）
  const items: React.ReactNode[] = useMemo(
    () =>
      segmentToolSteps(tools).map((seg, i) => {
        if (seg.kind === 'ask') {
          return <AskedQuestions key={`ask-${seg.steps[0]?.id ?? i}`} steps={seg.steps} />
        }
        if (seg.kind === 'grep') {
          return <GrepBatch key={`grep-${seg.steps[0]?.id ?? i}`} steps={seg.steps} />
        }
        if (seg.kind === 'skill') {
          return <SkillBatch key={`skill-${seg.steps[0]?.id ?? i}`} steps={seg.steps} />
        }
        if (seg.kind === 'task') {
          return <SubagentCard key={seg.step.id ?? seg.step.toolCallId ?? i} step={seg.step} />
        }
        return <ToolStepRow key={seg.step.id ?? seg.step.toolCallId ?? i} step={seg.step} />
      }),
    [tools],
  )

  return (
    <>
      {items.length > 0 && <div className="space-y-1">{items}</div>}
      {todos.length > 0 && (
        <Steps defaultOpen className="mt-2">
          <StepsTrigger className="text-xs">
            任务清单 · {done} / {total} 完成
          </StepsTrigger>
          <StepsContent bar={false}>
            {todos.map((t, i) => {
              const isDone = t.status === 'completed'
              const isDoing = t.status === 'in_progress'
              return (
                <StepsItem key={i}>
                  <span className="flex items-center gap-2">
                    <span
                      className={cn(
                        'flex h-4 w-4 flex-none items-center justify-center rounded-full text-[10px]',
                        isDone
                          ? 'bg-primary text-primary-foreground'
                          : isDoing
                            ? 'bg-muted text-muted-foreground'
                            : 'border border-line text-transparent',
                      )}
                    >
                      {isDone ? '✓' : isDoing ? '●' : '○'}
                    </span>
                    <span className={cn(isDone && 'text-muted-foreground/70 line-through')}>
                      {t.content}
                    </span>
                  </span>
                </StepsItem>
              )
            })}
          </StepsContent>
        </Steps>
      )}
    </>
  )
})
