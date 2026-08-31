import { memo, useState } from 'react'
import type { TodoItem, ToolStep } from '@/api/sse'
import { Brain, ChevronDown, MessageCircleQuestion } from 'lucide-react'
import { Steps, StepsContent, StepsItem, StepsTrigger } from '@/components/ai/Steps'
import { SubagentCard } from '@/components/ai/SubagentCard'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { MemoMarkdown } from '@/components/ai/MemoMarkdown'
import { stepArgLabel, toolDisplayName, toolIcon } from '@/components/ai/toolDisplay'
import { useAutoCollapse } from '@/hooks/useAutoCollapse'
import { humanizeError } from '@/lib/errorText'
import { mdRemarkPlugins } from '@/lib/markdown'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import ReactMarkdown from 'react-markdown'

/** 步骤思考折叠行：该工具调用前模型的一段思考（tool.called 封段写入 step.reasoning，
 *  与旁白封段同一条规则）。默认收起、点开看全文（定高滚动）——思考是辅助材料，
 *  流水结构（思考→工具→结果→思考）靠行序呈现。旧 trace 快照无此键，防御性跳过。
 *  memo：静态内容，流式期间父级重渲染不重解析 markdown。 */
export const StepThinking = memo(function StepThinking({ text }: { text?: string }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <Collapsible className="group" open={open} onOpenChange={setOpen}>
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
 *  完成后自动收缩（用户手动展开不被覆盖）。点击展开详情 = 关键参数（路径/问题等）+ 结果摘要/错误。 */
function ToolStepRow({ step }: { step: ToolStep }) {
  const [open, setOpen] = useAutoCollapse(step.status)
  const arg = stepArgLabel(step.tool, step.args)
  const Icon = toolIcon(step.tool)
  const statusText =
    step.status === 'running'
      ? '执行中'
      : step.status === 'error'
        ? '失败'
        : step.status === 'paused'
          ? '已暂停'
          : '成功'
  return (
    <Collapsible className="group" open={open} onOpenChange={setOpen}>
      <StepThinking text={step.reasoning} />
      <NarrationLine text={step.text} />
      <CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-1.5 py-0.5 text-left text-[13px] text-muted-foreground transition-colors hover:text-foreground">
        <Icon className="size-3.5 shrink-0" aria-hidden />
        {step.status === 'running' ? (
          <TextShimmer className="whitespace-nowrap">
            {toolDisplayName(step.tool)} · {statusText}
          </TextShimmer>
        ) : (
          <>
            <span className="whitespace-nowrap">{toolDisplayName(step.tool)}</span>
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
            <div className="art-result max-h-72 overflow-y-auto pr-1">{step.summary}</div>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** 已回答的提问折叠组（参考图「已询问 N 个问题」形态）：ask_human 步骤收拢为一组，
 *  每项 = 问题 + 你的回答（结果摘要即用户回答原文）。默认收起——回答过的问题不必
 *  常驻展开，转录里也不再渲染独立的「已选：」回答气泡。 */
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
                <div className="text-xs text-muted-foreground">你的回答：{s.summary}</div>
              )}
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** 执行过程流（工具行 + 任务清单）：RunMessage（运行中）与历史消息（trace 快照）共用。
 *  仿参考产品扁平时间线：旁白正文与工具行按序平铺（外层运行头负责折叠）。
 *  task 步骤渲染 SubagentCard（含子代理 children/reasoning），ask_human 步骤收进
 *  问答折叠组，其余工具渲染普通步骤行。
 *  memo：流式正文 token 期间 tools/todos 引用不变 → 整个过程区跳过重渲染
 *  （白名单制：新增 prop 必须是引用稳定或值类型，否则比较器要同步改）。 */
export const RunTrace = memo(function RunTrace({
  tools,
  todos,
  done = 0,
  total = 0,
}: {
  tools: ToolStep[]
  todos: TodoItem[]
  done?: number
  total?: number
}) {
  const items: React.ReactNode[] = []
  let askGroup: ToolStep[] = []
  const flushAsk = (at?: number) => {
    if (askGroup.length === 0) return
    const group = askGroup
    items.push(<AskedQuestions key={`ask-${group[0]?.id ?? at ?? 'x'}`} steps={group} />)
    askGroup = []
  }
  tools.forEach((s, i) => {
    if (s.tool === 'ask_human') {
      askGroup.push(s)
      return
    }
    flushAsk(i)
    if (s.tool === 'task') {
      items.push(<SubagentCard key={s.id ?? s.toolCallId ?? i} step={s} />)
    } else {
      items.push(<ToolStepRow key={s.id ?? s.toolCallId ?? i} step={s} />)
    }
  })
  flushAsk()

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
