import { useEffect, useRef } from 'react'
import { Brain } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import type { Message } from '@/api/client'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { RunTrace } from '@/components/ai/RunTrace'
import { Message as WMessage } from '@/components/workspace/Message'
import { mdRemarkPlugins } from '@/lib/markdown'

export const markdownComponents = {
  table: (props: React.ComponentPropsWithoutRef<'table'>) => (
    <div className="my-2 overflow-x-auto rounded-xl border bg-card">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  th: (props: React.ComponentPropsWithoutRef<'th'>) => (
    <th className="border px-3 py-1.5 text-left font-semibold" {...props} />
  ),
  td: (props: React.ComponentPropsWithoutRef<'td'>) => (
    <td className="border px-3 py-1.5 align-top" {...props} />
  ),
  a: (props: React.ComponentPropsWithoutRef<'a'>) => (
    <a className="text-primary underline" target="_blank" rel="noreferrer" {...props} />
  ),
  code: (props: React.ComponentPropsWithoutRef<'code'>) => (
    <code className="rounded bg-muted px-1 py-0.5 text-[0.9em]" {...props} />
  ),
}

const ASSISTANT_NAME = 'Tender Agent'

function AssistantFrame({ status, children }: { status?: React.ReactNode; children: React.ReactNode }) {
  return (
    <WMessage
      role="assistant"
      name={ASSISTANT_NAME}
      avatar={<div className="msg-avatar">T</div>}
      status={status}
    >
      {children}
    </WMessage>
  )
}

/** 用户消息：右对齐、panel-2 底、右上角小圆角气泡。 */
export function UserBubble({ content }: { content: string }) {
  return (
    <WMessage role="user">
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
          深度思考
        </span>
      </ReasoningTrigger>
      <ReasoningContent contentClassName="border-l-2 border-line pl-3">
        <div ref={scrollRef} className="max-h-72 overflow-y-auto pr-1 text-[13px] leading-relaxed">
          <ReactMarkdown remarkPlugins={mdRemarkPlugins}>{text}</ReactMarkdown>
        </div>
      </ReasoningContent>
    </Reasoning>
  )
}

/** 助手消息：左对齐通栏（不套气泡），白底透明，15px 行高 1.7。
 *  过程区仿参考产品扁平时间线：一个「已完成 · N 步」运行头统一折叠，内部按序平铺
 *  深度思考块（border-left）→ 工具行流（旁白正文穿插）→ 任务清单；最终正文在折叠区外。 */
export function AssistantMessage({ content, tools, todos, reasoning }: { content: string; tools?: Message['tools']; todos?: Message['todos']; reasoning?: string | null }) {
  const done = tools?.filter((t) => t.status !== 'running').length ?? 0
  const hasProcess = Boolean(reasoning?.trim()) || Boolean(tools?.length) || Boolean(todos?.length)
  return (
    <AssistantFrame>
      {hasProcess && (
        <Reasoning isStreaming={false} className="mb-1.5">
          <ReasoningTrigger className="text-sm text-muted-foreground">
            已完成{tools?.length ? ` · ${tools.length} 步` : ''}
          </ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2 space-y-2">
            {reasoning?.trim() && <DeepThinking text={reasoning} />}
            {tools && tools.length > 0 && (
              <RunTrace tools={tools} todos={todos ?? []} done={done} total={tools.length} />
            )}
          </ReasoningContent>
        </Reasoning>
      )}
      <div className="bubble">
        <ReactMarkdown remarkPlugins={mdRemarkPlugins} components={markdownComponents}>
          {content}
        </ReactMarkdown>
      </div>
    </AssistantFrame>
  )
}

export function ChatMessage({ message }: { message: Message }) {
  return message.role === 'user' ? (
    <UserBubble content={message.content} />
  ) : (
    <AssistantMessage
      content={message.content}
      tools={message.tools}
      todos={message.todos}
      reasoning={message.reasoning}
    />
  )
}
