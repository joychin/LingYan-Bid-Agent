import { memo } from 'react'
import { Bot, CheckCircle, ChevronDown, CirclePause, Loader2, XCircle } from 'lucide-react'
import { Loader } from '@/components/ai/Loader'
import { MemoMarkdown } from '@/components/ai/MemoMarkdown'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { subagentStepTitle, toolDisplayName } from '@/components/ai/toolDisplay'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import type { ToolStep } from '@/api/sse'
import { useAutoCollapse } from '@/hooks/useAutoCollapse'
import { useThrottledValue } from '@/hooks/useThrottledValue'
import { humanizeError } from '@/lib/errorText'
import { capStreamingText } from '@/lib/streamTextCap'
import { cn } from '@/lib/utils'

/** 子代理内部工具步骤行：图标 + 名称 + 状态，点击看结果。 */
function ChildStep({ step }: { step: ToolStep }) {
  const [open, setOpen] = useAutoCollapse(step.status)
  const isRunning = step.status === 'running'
  const isError = step.status === 'error'
  const isPaused = step.status === 'paused'
  const statusText = isRunning ? '执行中' : isError ? '失败' : isPaused ? '已暂停' : '已完成'
  return (
    <Collapsible className="group" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-2 py-0.5 text-left text-[12.5px] text-muted-foreground transition-colors hover:text-foreground">
        {isRunning ? (
          <Loader variant="circular" size="xs" className="shrink-0" />
        ) : isError ? (
          <XCircle className="size-3 shrink-0 text-red-500" />
        ) : isPaused ? (
          <CirclePause className="size-3 shrink-0 text-muted-foreground" />
        ) : (
          <CheckCircle className="size-3 shrink-0 text-success" />
        )}
        {isRunning ? (
          <TextShimmer className="truncate">
            {toolDisplayName(step.tool)} · {statusText}
          </TextShimmer>
        ) : (
          <>
            <span className="truncate">{toolDisplayName(step.tool)}</span>
            <span className="shrink-0 text-xs text-muted-foreground/60">· {statusText}</span>
          </>
        )}
        <ChevronDown className="ml-auto size-3.5 shrink-0 text-muted-foreground/40 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden">
        <div className="ml-4 space-y-1 border-l border-line py-0.5 pl-2 text-[12px] text-muted-foreground">
          {isError && step.error ? (
            // 首屏人话 + 原始错误详情（同 ToolStepRow；超长原文定高滚动防撑开卡片）
            <div className="max-h-40 overflow-y-auto pr-1">
              <p className="whitespace-pre-wrap break-all" style={{ color: 'var(--Color-danger)' }}>
                {humanizeError(step.error)}
              </p>
              <p className="whitespace-pre-wrap break-all text-muted-foreground/60">{step.error}</p>
            </div>
          ) : step.summary ? (
            <p className="art-result line-clamp-6 whitespace-pre-wrap break-all">{step.summary}</p>
          ) : isRunning ? (
            <p className="flex items-center gap-1.5 text-muted-foreground/60">
              <Loader variant="dots" size="xs" />
              执行中
            </p>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** 子代理思考块：reasoning 是流式 token 热路径（多册并发派发时的主 token 通道），
 *  节流（渲染层合并）+ 分块 memo（只重解析最后一块）双重降本。
 *  流式期间只渲染尾部（capStreamingText）：活卡思考 DOM 与重解析成本不随 run
 *  无界增长（2026-09-08 内存暴涨修复）；终态渲染全文（数据源已是服务端快照）。 */
function StepReasoning({ text, isStreaming }: { text: string; isStreaming: boolean }) {
  const shown = useThrottledValue(text)
  const display = isStreaming ? capStreamingText(shown).text : shown
  return (
    <Reasoning isStreaming={isStreaming}>
      <ReasoningTrigger className="text-xs text-muted-foreground">
        {isStreaming ? <TextShimmer>思考过程</TextShimmer> : '思考过程'}
      </ReasoningTrigger>
      <ReasoningContent contentClassName="mt-1 text-[12px] leading-relaxed">
        <MemoMarkdown text={display} />
      </ReasoningContent>
    </Reasoning>
  )
}

/** 子代理任务卡：task 工具的专属渲染（其余工具走 ToolStepRow）。
 *  折叠 = 一行流（分支图标 + 短名 + 状态徽章，短名取 description 首行，
 *  规则见 toolDisplay.subagentStepTitle，完整描述在展开区）；
 *  展开 = 子代理 reasoning（折叠）
 *  + 内部工具调用序列 + 最终报告/错误；展开内容限高滚动（更多内容下翻查看）；
 *  完成后自动收缩（用户手动展开不被覆盖）。
 *  数据契约：tool.called 的 args={description, subagent_type}；子代理内部事件以
 *  agent_id=本卡 tool_call_id 归属（children/reasoning）；tool.result 的 summary/error。
 *  memo：兄弟卡在别的子代理 reasoning 流式时引用不变（appendReasoning 保留未命中步骤
 *  引用）→ 本卡跳过重渲染；本卡自己的 step 引用变化时照常更新。 */
export const SubagentCard = memo(function SubagentCard({ step }: { step: ToolStep }) {
  const [open, setOpen] = useAutoCollapse(step.status)
  const description = typeof step.args?.description === 'string' ? step.args.description : ''
  const subagentType = typeof step.args?.subagent_type === 'string' ? step.args.subagent_type : ''
  const shortName = subagentStepTitle(step.args) || toolDisplayName('task')
  const isRunning = step.status === 'running'
  const isStarting = isRunning && step.children.length === 0 && !step.reasoning
  const isError = step.status === 'error'
  const isPaused = step.status === 'paused'
  // 门禁冻结（审批前快照）：paused 且无任何执行痕迹（children/reasoning）= 尚未真正
  // 运行过、在等用户批准；有执行痕迹的 paused 才是「运行中途被打断」。
  const awaitingApproval = isPaused && step.children.length === 0 && !step.reasoning

  return (
    <Collapsible className="group cv-step" open={open} onOpenChange={setOpen}>
      {step.text ? (
        <p className="whitespace-pre-wrap py-0.5 text-[13px] leading-relaxed text-muted-foreground">
          {step.text}
        </p>
      ) : null}
      <CollapsibleTrigger
        title="子代理任务（task 工具派生，独立上下文执行）"
        className="flex w-full cursor-pointer items-center gap-2 py-0.5 text-left text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <Bot className="size-4 shrink-0 text-primary" aria-label="子代理任务" />
        {isRunning ? (
          <TextShimmer className="min-w-0 flex-1 truncate">{shortName}</TextShimmer>
        ) : (
          <span className="min-w-0 flex-1 truncate">{shortName}</span>
        )}
        <span
          className={cn(
            'inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
            isRunning
              ? 'bg-blue-100 text-blue-700'
              : isError
                ? 'bg-red-100 text-red-700'
                : isPaused
                  ? 'bg-muted text-muted-foreground'
                  : 'bg-success-soft text-success',
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
          {isRunning
            ? isStarting
              ? '启动中'
              : '运行中'
            : isError
              ? '失败'
              : awaitingApproval
                ? '等待确认'
                : isPaused
                  ? '已暂停'
                  : '已完成'}
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground/50 transition-transform group-data-[state=open]:rotate-180" />
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
          {step.reasoning && <StepReasoning text={step.reasoning} isStreaming={isRunning} />}
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
            <>
              <p className="art-result" style={{ color: 'var(--Color-danger)' }}>
                {humanizeError(step.error)}
              </p>
              <p className="art-result break-all text-xs text-muted-foreground/70">{step.error}</p>
            </>
          ) : isRunning ? (
            // div 非 p：内嵌 Loader 渲染 div，p>div 是非法 HTML 嵌套（控制台报错）
            <div className="flex items-center gap-1 text-[13px] text-muted-foreground/70">
              <Loader variant="loading-dots" text={isStarting ? '子代理启动中' : '子代理执行中'} size="sm" />
              结果回传后显示在这里
            </div>
          ) : step.summary ? (
            <p className="art-result">{step.summary}</p>
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
})
