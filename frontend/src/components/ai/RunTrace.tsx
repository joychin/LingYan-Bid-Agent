import type { TodoItem, ToolStep } from '@/api/sse'
import { ChainOfThought, ChainOfThoughtContent, ChainOfThoughtStep, ChainOfThoughtTrigger } from '@/components/ai/ChainOfThought'
import { Duration } from '@/components/ai/Duration'
import { Steps, StepsContent, StepsItem, StepsTrigger } from '@/components/ai/Steps'
import { SubagentCard } from '@/components/ai/SubagentCard'
import { stepArgLabel, toolDisplayName } from '@/components/ai/toolDisplay'
import { useAutoCollapse } from '@/hooks/useAutoCollapse'
import { cn } from '@/lib/utils'

/** 步骤前旁白行：该工具调用前模型输出的一句过程说明（tool.called 封段写入 step.text）。
 *  旧 trace 快照无此键，防御性跳过。 */
function NarrationLine({ text }: { text?: string }) {
  if (!text) return null
  return (
    <p className="whitespace-pre-wrap py-0.5 text-[13px] leading-relaxed text-muted-foreground">
      {text}
    </p>
  )
}

/** 普通工具步骤行：完成后自动收缩（用户手动展开不被覆盖）。参数（路径等）跟在标签后。 */
function ToolStepRow({ step }: { step: ToolStep }) {
  const [open, setOpen] = useAutoCollapse(step.status)
  const arg = stepArgLabel(step.tool, step.args)
  const statusText =
    step.status === 'running'
      ? '执行中'
      : step.status === 'error'
        ? '失败'
        : step.status === 'paused'
          ? '已暂停'
          : '成功'
  return (
    <ChainOfThoughtStep open={open} onOpenChange={setOpen}>
      <NarrationLine text={step.text} />
      <ChainOfThoughtTrigger>
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span className="whitespace-nowrap">{toolDisplayName(step.tool)}</span>
          {arg && (
            <span
              className="min-w-0 truncate font-mono text-xs text-muted-foreground/80"
              title={arg}
            >
              {arg}
            </span>
          )}
          <span className="whitespace-nowrap">· {statusText}</span>
        </span>
        <Duration startedAt={step.startedAt} endedAt={step.endedAt} className="ml-1" />
      </ChainOfThoughtTrigger>
      <ChainOfThoughtContent>
        {step.status === 'error' && step.error ? (
          <div className="art-result" style={{ color: 'var(--error)' }}>
            {step.error}
          </div>
        ) : step.summary ? (
          <div className="art-result">{step.summary}</div>
        ) : null}
      </ChainOfThoughtContent>
    </ChainOfThoughtStep>
  )
}

/** 执行过程块（工具时间线 + 任务清单）：RunMessage（运行中）与历史消息（trace 快照）共用。
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
        <ChainOfThought>
          {tools.map((s, i) =>
            s.tool === 'task' ? (
              <SubagentCard key={s.id ?? s.toolCallId ?? i} step={s} />
            ) : (
              <ToolStepRow key={s.id ?? s.toolCallId ?? i} step={s} />
            ),
          )}
        </ChainOfThought>
      )}
      {todos.length > 0 && (
        <Steps defaultOpen className="mt-2">
          <StepsTrigger className="text-xs">
            任务清单 · {done} / {total} 完成
          </StepsTrigger>
          <StepsContent>
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
