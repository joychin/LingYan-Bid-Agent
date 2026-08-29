import { CheckCircle, ChevronDown, CirclePause, GitBranch, Loader2, XCircle } from 'lucide-react'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { toolDisplayName } from '@/components/ai/toolDisplay'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { ToolStep } from '@/api/sse'
import { useAutoCollapse } from '@/hooks/useAutoCollapse'
import { cn } from '@/lib/utils'

/** 子代理内部工具步骤行：图标 + 名称 + 状态，点击看结果。 */
function ChildStep({ step }: { step: ToolStep }) {
  const [open, setOpen] = useAutoCollapse(step.status)
  const isRunning = step.status === 'running'
  const isError = step.status === 'error'
  const isPaused = step.status === 'paused'
  const statusText = isRunning ? '执行中' : isError ? '失败' : isPaused ? '已暂停' : '成功'
  return (
    <Collapsible className="group" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-2 py-0.5 text-left text-[12.5px] text-muted-foreground transition-colors hover:text-foreground">
        {isRunning ? (
          <Loader2 className="size-3 shrink-0 animate-spin text-blue-500" />
        ) : isError ? (
          <XCircle className="size-3 shrink-0 text-red-500" />
        ) : isPaused ? (
          <CirclePause className="size-3 shrink-0 text-muted-foreground" />
        ) : (
          <CheckCircle className="size-3 shrink-0 text-emerald-500" />
        )}
        <span className="truncate">{toolDisplayName(step.tool)}</span>
        <span className="shrink-0 text-xs text-muted-foreground/60">· {statusText}</span>
        <ChevronDown className="ml-auto size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden">
        <div className="ml-4 space-y-1 border-l border-line py-0.5 pl-2 text-[12px] text-muted-foreground">
          {isError && step.error ? (
            <p className="whitespace-pre-wrap break-all" style={{ color: 'var(--error)' }}>{step.error}</p>
          ) : step.summary ? (
            <p className="art-result line-clamp-6 whitespace-pre-wrap break-all">{step.summary}</p>
          ) : isRunning ? (
            <p className="text-muted-foreground/60">执行中…</p>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** 子代理任务卡：task 工具的专属渲染（其余工具走 ToolStepRow）。
 *  折叠 = 一行流（分支图标 + 工具名 + 状态徽章，不展示业务内容，任务描述在展开区）；
 *  展开 = 子代理 reasoning（折叠）
 *  + 内部工具调用序列 + 最终报告/错误；展开内容限高滚动（更多内容下翻查看）；
 *  完成后自动收缩（用户手动展开不被覆盖）。
 *  数据契约：tool.called 的 args={description, subagent_type}；子代理内部事件以
 *  agent_id=本卡 tool_call_id 归属（children/reasoning）；tool.result 的 summary/error。 */
export function SubagentCard({ step }: { step: ToolStep }) {
  const [open, setOpen] = useAutoCollapse(step.status)
  const description = typeof step.args?.description === 'string' ? step.args.description : ''
  const subagentType = typeof step.args?.subagent_type === 'string' ? step.args.subagent_type : ''
  const isRunning = step.status === 'running'
  const isError = step.status === 'error'
  const isPaused = step.status === 'paused'

  return (
    <Collapsible className="group" open={open} onOpenChange={setOpen}>
      {step.text ? (
        <p className="whitespace-pre-wrap py-0.5 text-[13px] leading-relaxed text-muted-foreground">
          {step.text}
        </p>
      ) : null}
      <CollapsibleTrigger
        title="子代理任务（task 工具派生，独立上下文执行）"
        className="flex w-full cursor-pointer items-center gap-2 py-0.5 text-left text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <GitBranch className="size-4 shrink-0 text-primary" aria-label="子代理任务" />
        <span className="whitespace-nowrap">{toolDisplayName('task')}</span>
        <span
          className={cn(
            'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
            isRunning
              ? 'bg-blue-100 text-blue-700'
              : isError
                ? 'bg-red-100 text-red-700'
                : isPaused
                  ? 'bg-muted text-muted-foreground'
                  : 'bg-emerald-100 text-emerald-700',
          )}
        >
          {isRunning ? (
            <Loader2 className="size-3 animate-spin" />
          ) : isError ? (
            <XCircle className="size-3" />
          ) : isPaused ? (
            <CirclePause className="size-3" />
          ) : (
            <CheckCircle className="size-3" />
          )}
          {isRunning ? '运行中' : isError ? '失败' : isPaused ? '已暂停' : '已完成'}
        </span>
        <ChevronDown className="ml-auto size-4 shrink-0 text-muted-foreground/50 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden">
        <div className="max-h-72 space-y-2 overflow-y-auto py-1 pr-1">
          {subagentType && (
            <p className="font-mono text-[11px] text-muted-foreground/70">[{subagentType}]</p>
          )}
          {description && (
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-muted-foreground">
              {description}
            </p>
          )}
          {step.reasoning && (
            <Reasoning isStreaming={isRunning}>
              <ReasoningTrigger className="text-xs text-muted-foreground">子代理思考过程</ReasoningTrigger>
              <ReasoningContent contentClassName="mt-1 text-[12px] leading-relaxed" markdown>
                {step.reasoning}
              </ReasoningContent>
            </Reasoning>
          )}
          {step.children.length > 0 && (
            <div className="space-y-0.5">
              {step.children.map((c, i) =>
                c.tool === 'task' ? (
                  <SubagentCard key={c.id ?? c.toolCallId ?? i} step={c} />
                ) : (
                  <ChildStep key={c.id ?? c.toolCallId ?? i} step={c} />
                ),
              )}
            </div>
          )}
          {isError && step.error ? (
            <p className="art-result" style={{ color: 'var(--error)' }}>
              {step.error}
            </p>
          ) : isRunning ? (
            <p className="text-[13px] text-muted-foreground/70">
              子代理执行中…结果回传后显示在这里
            </p>
          ) : step.summary ? (
            <p className="art-result">{step.summary}</p>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
