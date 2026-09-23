import { memo, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Brain, Check, Copy } from 'lucide-react'
import type { Message } from '@/api/client'
import { fetchMessageTrace } from '@/api/client'
import { Loader } from '@/components/ai/Loader'
import { MessageAction, MessageActions, useCopyToClipboard } from '@/components/ai/MessageActions'
import { MemoMarkdown, markdownComponents } from '@/components/ai/MemoMarkdown'
import { NarrationLine } from '@/components/ai/RunTrace'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { RunFiles } from '@/components/ai/RunFiles'
import { RunTrace } from '@/components/ai/RunTrace'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { Message as WMessage } from '@/components/workspace/Message'
import { ASSISTANT_NAME } from '@/lib/brand'
import { splitMarker, MARKER_CHIP, type PauseMarker } from '@/lib/hitlMessage'
import { capStreamingText } from '@/lib/streamTextCap'

/** 复制按钮（copied 2s 反馈：Copy→Check）。align 随所在行位置防 tooltip 溢出。 */
function CopyAction({ content, align }: { content: string; align: 'start' | 'end' }) {
  const { copied, copy } = useCopyToClipboard()
  return (
    <MessageAction
      tooltip={copied ? '已复制' : '复制'}
      align={align}
      className={copied ? 'text-foreground' : undefined}
      onClick={() => void copy(content)}
    >
      {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
    </MessageAction>
  )
}

/** 消息操作条通用显隐：hover/键盘聚焦淡入（opacity 不 display 切换，同侧栏按钮先例）。 */
function HoverActions({ children }: { children: React.ReactNode }) {
  return (
    <MessageActions className="mt-1 opacity-0 transition-opacity duration-150 group-focus-within/msg:opacity-100 group-hover/msg:opacity-100">
      {children}
    </MessageActions>
  )
}

function AssistantFrame({
  status,
  children,
  attach,
}: {
  status?: React.ReactNode
  children: React.ReactNode
  /** 回合续段（同 run 的暂停段之后的段落）：不渲染头像/名字头，正文与回合头对齐。 */
  attach?: boolean
}) {
  return (
    <WMessage
      role="assistant"
      name={attach ? undefined : ASSISTANT_NAME}
      avatar={attach ? <div className="msg-spacer" aria-hidden /> : <div className="msg-avatar" aria-hidden />}
      status={status}
    >
      {children}
    </WMessage>
  )
}

/** 用户消息：右对齐、panel-2 底、右上角小圆角气泡。 */
export function UserBubble({ content }: { content: string }) {
  return (
    <WMessage
      role="user"
      actions={
        <HoverActions>
          <div className="flex-1" />
          <CopyAction content={content} align="end" />
        </HoverActions>
      }
    >
      <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{content}</p>
    </WMessage>
  )
}

/** 深度思考折叠区（主 agent reasoning）：运行中（RunMessage）与历史（AssistantMessage）共用。
 *  内容区 border-left 竖线（同参考产品 thinking 样式）+ 定高 288px 滚动（滚动层在动画容器内
 *  互不干扰）；autoFollow = 流式增长时视口贴底。isStreaming 翻 false 时自动收起——保留折叠入口。 */
export function DeepThinking({
  text,
  isStreaming,
  autoFollow = false,
}: {
  text: string
  isStreaming?: boolean
  autoFollow?: boolean
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (autoFollow && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [text, autoFollow])
  // 流式期间只渲染尾部（2026-09-08 内存暴涨修复，同 StepReasoning）；autoFollow
  // 贴底仍按全文长度触发（尾部也在长），终态/历史渲染全文
  const display = isStreaming ? capStreamingText(text).text : text
  return (
    <Reasoning isStreaming={isStreaming} className="mb-1.5">
      <ReasoningTrigger className="text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Brain className="size-3.5 shrink-0" aria-hidden />
          {isStreaming ? <TextShimmer>深度思考</TextShimmer> : '深度思考'}
        </span>
      </ReasoningTrigger>
      <ReasoningContent contentClassName="border-l-2 border-line pl-3">
        <div ref={scrollRef} className="max-h-72 overflow-y-auto pr-1 text-[13px] leading-relaxed">
          {/* 过程稿免责一行（2026-09-23 B4）：思考是模型内心戏原样记录（中英混杂、
              未定稿自言自语），先声明预期再展示，避免被当成正式内容 */}
          <p className="pb-1 text-xs text-muted-foreground/60">模型过程草稿，非最终内容</p>
          <MemoMarkdown text={display} />
        </div>
      </ReasoningContent>
    </Reasoning>
  )
}

/** 历史中断消息的重跑动作（2026-09-12）：转录里「已中断」的最后一个回合给出
 *  一键续接入口——错误卡是内存态，刷新后消失，此前用户只能手动重打原话。
 *  label 由调用方给（重新执行 / 从断点继续），点击行为也由调用方接线。 */
export interface InterruptAction {
  label: string
  onRun: () => void
}

/** 助手消息：左对齐通栏（不套气泡），白底透明，15px 行高 1.7。
 *  过程区仿参考产品扁平时间线：一个「已完成/已暂停 · N 步」运行头统一折叠，内部按序平铺
 *  深度思考块（border-left）→ 工具行流（旁白正文穿插）→ 任务清单；最终正文在折叠区外。
 *  attach=回合续段（无头像头）。
 *  暂停/中断消息（半截落库）：不渲染正文气泡——正文作为旁白行进过程卡、标记成
 *  卡内徽章（HITL 痕迹全部收进过程区，正文区只留模型的最终回复）。
 *  pauseNarration/pauseMarker：同回合被吸收的暂停段上提的旁白与标记（MessageList
 *  装配，见 ChatView）——全回合只渲染一张过程卡。 */
export function AssistantMessage({
  message,
  attach,
  pauseNarration,
  pauseMarker,
  interruptAction,
  onOpenWorkbench,
}: {
  message: Message
  attach?: boolean
  pauseNarration?: string
  pauseMarker?: PauseMarker
  /** 中断回合的一键续接入口：仅转录最后一个「已中断」回合携带（MessageList 定位） */
  interruptAction?: InterruptAction | null
  /** 「本轮文件」chip -> 工作台面板编辑 */
  onOpenWorkbench?: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  // 过程快照按需取（2026-09-08 messages 瘦身）：列表只带步数/暂停摘要，点开过程区
  // 才拉完整 tools/todos/reasoning。run 终态后快照不再变——staleTime 永久；缓存保留
  // 10 分钟（3GB 内存修复批从 30min 收窄：长会话翻旧过程不再多份全量 trace 长驻，
  // 过期重开也只是再拉一次本地请求）。
  const traceQuery = useQuery({
    queryKey: ['message-trace', message.id],
    queryFn: () => fetchMessageTrace(message.conversation_id, message.id),
    enabled: open,
    staleTime: Infinity,
    gcTime: 10 * 60_000,
    retry: 1,
  })
  const trace = traceQuery.data
  const { body, marker } = splitMarker(message.content)
  const isMarked = marker !== null
  const chipMarker = marker ?? (pauseMarker ?? null)
  // traceSteps 非 null = 有 run_traces 行（steps 可为 0：纯思考无工具的 run）
  const hasProcess =
    isMarked || !!chipMarker || !!pauseNarration?.trim() || message.traceSteps != null
  return (
    <AssistantFrame attach={attach}>
      {hasProcess && (
        <Reasoning isStreaming={false} className="mb-1.5" open={open} onOpenChange={setOpen}>
          <ReasoningTrigger className="text-sm text-muted-foreground">
            {(message.tracePaused || marker === 'pause') ? '已暂停' : marker === 'interrupted' ? '已中断' : '已完成'}
            {message.traceSteps ? ` · ${message.traceSteps} 步` : ''}
          </ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2 space-y-2">
            {/* 标记消息（暂停/中断半截）正文升为消息气泡（2026-09-23 A1 修复：
                确认门「概况如上」要真的看得到），过程区不再重复一行旁白 */}
            {pauseNarration?.trim() && <NarrationLine text={pauseNarration} />}
            {open && traceQuery.isPending && (
              <div className="flex items-center gap-1.5 py-0.5 text-[13px] text-muted-foreground/70">
                <Loader variant="dots" size="xs" /> 正在载入执行过程…
              </div>
            )}
            {open && traceQuery.isError && (
              <button
                type="button"
                className="cursor-pointer py-0.5 text-left text-[13px] text-muted-foreground/70 transition-colors hover:text-foreground"
                onClick={() => void traceQuery.refetch()}
              >
                执行过程载入失败，点击重试
              </button>
            )}
            {trace && trace.tools.length > 0 && (
              <RunTrace
                tools={trace.tools}
                todos={trace.todos}
                done={trace.tools.filter((t) => t.status !== 'running').length}
                total={trace.tools.length}
              />
            )}
            {/* 历史思考块：新数据=最终回复前的未封口段（逐段思考已沉入步骤行），
                旧 trace 快照=整段累积（位置移到步骤区之后，内容不丢） */}
            {trace?.reasoning.trim() && <DeepThinking text={trace.reasoning} />}
            {chipMarker && <div className="turn-chip">{MARKER_CHIP[chipMarker]}</div>}
          </ReasoningContent>
        </Reasoning>
      )}
      {body.trim() && (
        <div className="bubble">
          <MemoMarkdown text={body} components={markdownComponents} />
        </div>
      )}
      {interruptAction && (
        <button
          type="button"
          className="mt-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
          onClick={interruptAction.onRun}
        >
          {interruptAction.label}
        </button>
      )}
      <RunFiles files={message.files} onOpen={onOpenWorkbench} />
      {message.content.trim() && (
        <HoverActions>
          <CopyAction content={body} align="start" />
        </HoverActions>
      )}
    </AssistantFrame>
  )
}

export const ChatMessage = memo(
  function ChatMessage({
    message,
    attach = false,
    pauseNarration,
    pauseMarker,
    interruptAction,
    onOpenWorkbench,
  }: {
    message: Message
    attach?: boolean
    pauseNarration?: string
    pauseMarker?: PauseMarker
    interruptAction?: InterruptAction | null
    onOpenWorkbench?: (path: string) => void
  }) {
    return message.role === 'user' ? (
      <UserBubble content={message.content} />
    ) : (
      <AssistantMessage
        message={message}
        attach={attach}
        pauseNarration={pauseNarration}
        pauseMarker={pauseMarker}
        interruptAction={interruptAction}
        onOpenWorkbench={onOpenWorkbench}
      />
    )
  },
  // 白名单比较器：流式 token 期间 messages 引用稳定（react-query structural sharing）
  // -> 历史消息全部跳过重渲染（含各自的 ReactMarkdown 重解析）。新增 prop 必须同步进
  // 比较器，否则新属性不更新 UI。
  (prev, next) =>
    prev.message === next.message &&
    prev.attach === next.attach &&
    prev.pauseNarration === next.pauseNarration &&
    prev.pauseMarker === next.pauseMarker &&
    prev.interruptAction === next.interruptAction &&
    prev.onOpenWorkbench === next.onOpenWorkbench,
)
