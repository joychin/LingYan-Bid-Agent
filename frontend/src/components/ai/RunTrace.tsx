import type { TodoItem, ToolStep } from '@/api/sse'
import { ChevronDown } from 'lucide-react'
import { Steps, StepsContent, StepsItem, StepsTrigger } from '@/components/ai/Steps'
import { SubagentCard } from '@/components/ai/SubagentCard'
import { stepArgLabel, toolDisplayName, toolIcon } from '@/components/ai/toolDisplay'
import { useAutoCollapse } from '@/hooks/useAutoCollapse'
import { mdRemarkPlugins } from '@/lib/markdown'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import ReactMarkdown from 'react-markdown'

/** 步骤前旁白行：该工具调用前模型输出的一句过程说明（tool.called 封段写入 step.text）。
 *  旧 trace 快照无此键，防御性跳过。正文样式（深色正文号，同参考产品的流内叙述段），
 *  按 markdown 渲染（旁白里的 **加粗** 不再裸露）。 */
function NarrationLine({ text }: { text?: string }) {
  if (!text) return null
  return (
    <div className="py-1 text-[15px] leading-relaxed text-foreground">
      <ReactMarkdown remarkPlugins={mdRemarkPlugins}>{text}</ReactMarkdown>
    </div>
  )
}

/** 普通工具步骤行：标题只显示「工具名 · 状态」（不展示业务内容），完成后自动收缩
 *  （用户手动展开不被覆盖）。点击展开详情 = 关键参数（路径/问题等）+ 结果摘要/错误。 */
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
      <NarrationLine text={step.text} />
      <CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-1.5 py-0.5 text-left text-[13px] text-muted-foreground transition-colors hover:text-foreground">
        <Icon className="size-3.5 shrink-0" aria-hidden />
        <span className="whitespace-nowrap">{toolDisplayName(step.tool)}</span>
        <span className="whitespace-nowrap">· {statusText}</span>
        <ChevronDown className="size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden">
        <div className="py-0.5 pl-3.5 pr-2">
          {arg && (
            <div className="break-all font-mono text-xs text-muted-foreground/80">{arg}</div>
          )}
          {step.status === 'error' && step.error ? (
            <div className="art-result" style={{ color: 'var(--error)' }}>
              {step.error}
            </div>
          ) : step.summary ? (
            <div className="art-result">{step.summary}</div>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** 执行过程流（工具行 + 任务清单）：RunMessage（运行中）与历史消息（trace 快照）共用。
 *  仿参考产品扁平时间线：旁白正文与工具行按序平铺（外层运行头负责折叠）。
 *  task 步骤渲染 SubagentCard（含子代理 children/reasoning），其余工具渲染普通步骤行。 */
export function RunTrace({
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
  return (
    <>
      {tools.length > 0 && (
        <div className="space-y-1">
          {tools.map((s, i) =>
            s.tool === 'task' ? (
              <SubagentCard key={s.id ?? s.toolCallId ?? i} step={s} />
            ) : (
              <ToolStepRow key={s.id ?? s.toolCallId ?? i} step={s} />
            ),
          )}
        </div>
      )}
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
}
