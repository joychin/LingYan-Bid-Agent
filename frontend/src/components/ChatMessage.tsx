import { memo, useEffect, useRef } from 'react'
import { Brain, Check, Copy } from 'lucide-react'
import type { Message } from '@/api/client'
import { MessageAction, MessageActions, useCopyToClipboard } from '@/components/ai/MessageActions'
import { MemoMarkdown, markdownComponents } from '@/components/ai/MemoMarkdown'
import { NarrationLine } from '@/components/ai/RunTrace'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { RunTrace } from '@/components/ai/RunTrace'
import { TextShimmer } from '@/components/ai/TextShimmer'
import { Message as WMessage } from '@/components/workspace/Message'
import { splitMarker, MARKER_CHIP, type PauseMarker } from '@/lib/hitlMessage'

const ASSISTANT_NAME = 'Tender Agent'

/** 树里是否有 paused 步骤（HITL 中断快照）——trace 折叠头区分「已暂停/已完成」。 */
function anyPaused(steps: readonly { status?: string; children?: unknown[] }[] | undefined | null): boolean {
  return !!steps?.some(
    (s) => s.status === 'paused' || anyPaused(s.children as { status?: string; children?: unknown[] }[]),
  )
}

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
      avatar={attach ? <div className="msg-spacer" aria-hidden /> : <div className="msg-avatar">T</div>}
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
          <MemoMarkdown text={text} />
        </div>
      </ReasoningContent>
    </Reasoning>
  )
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
  content,
  tools,
  todos,
  reasoning,
  attach,
  pauseNarration,
  pauseMarker,
}: {
  content: string
  tools?: Message['tools']
  todos?: Message['todos']
  reasoning?: string | null
  attach?: boolean
  pauseNarration?: string
  pauseMarker?: PauseMarker
}) {
  const done = tools?.filter((t) => t.status !== 'running').length ?? 0
  const { body, marker } = splitMarker(content)
  const isMarked = marker !== null
  const chipMarker = marker ?? (pauseMarker ?? null)
  const hasProcess =
    isMarked ||
    !!chipMarker ||
    !!pauseNarration?.trim() ||
    Boolean(reasoning?.trim()) ||
    Boolean(tools?.length) ||
    Boolean(todos?.length)
  return (
    <AssistantFrame attach={attach}>
      {hasProcess && (
        <Reasoning isStreaming={false} className="mb-1.5">
          <ReasoningTrigger className="text-sm text-muted-foreground">
            {anyPaused(tools) || marker === 'pause' ? '已暂停' : marker === 'interrupted' ? '已中断' : '已完成'}
            {tools?.length ? ` · ${tools.length} 步` : ''}
          </ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2 space-y-2">
            {isMarked && body.trim() && <NarrationLine text={body} />}
            {pauseNarration?.trim() && <NarrationLine text={pauseNarration} />}
            {reasoning?.trim() && <DeepThinking text={reasoning} />}
            {tools && tools.length > 0 && (
              <RunTrace tools={tools} todos={todos ?? []} done={done} total={tools.length} />
            )}
            {chipMarker && <div className="turn-chip">{MARKER_CHIP[chipMarker]}</div>}
          </ReasoningContent>
        </Reasoning>
      )}
      {!isMarked && (
        <div className="bubble">
          <MemoMarkdown text={body} components={markdownComponents} />
        </div>
      )}
      {content.trim() && (
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
  }: {
    message: Message
    attach?: boolean
    pauseNarration?: string
    pauseMarker?: PauseMarker
  }) {
    return message.role === 'user' ? (
      <UserBubble content={message.content} />
    ) : (
      <AssistantMessage
        content={message.content}
        tools={message.tools}
        todos={message.todos}
        reasoning={message.reasoning}
        attach={attach}
        pauseNarration={pauseNarration}
        pauseMarker={pauseMarker}
      />
    )
  },
  // 白名单比较器：流式 token 期间 messages 引用稳定（react-query structural sharing）
  // → 历史消息全部跳过重渲染（含各自的 ReactMarkdown 重解析）。新增 prop 必须同步进
  // 比较器，否则新属性不更新 UI。
  (prev, next) =>
    prev.message === next.message &&
    prev.attach === next.attach &&
    prev.pauseNarration === next.pauseNarration &&
    prev.pauseMarker === next.pauseMarker,
)
