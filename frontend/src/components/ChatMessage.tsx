import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Message } from '@/api/client'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { RunTrace } from '@/components/ai/RunTrace'
import { Message as WMessage } from '@/components/workspace/Message'
import { mdRemarkPlugins } from '@/lib/markdown'
import { formatDuration } from '@/lib/utils'

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
 *  内容区定高 288px 滚动（与 tool use 输出同款 max-h-72，滚动层在动画容器内互不干扰）；
 *  autoFollow = 流式增长时视口贴底。isStreaming 翻 false 时自动收起——保留折叠入口，不隐藏。 */
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
      <ReasoningTrigger className="text-sm text-foreground">深度思考</ReasoningTrigger>
      <ReasoningContent contentClassName="mt-2">
        <div ref={scrollRef} className="max-h-72 overflow-y-auto pr-1 text-[13px] leading-relaxed">
          <ReactMarkdown remarkPlugins={mdRemarkPlugins}>{text}</ReactMarkdown>
        </div>
      </ReasoningContent>
    </Reasoning>
  )
}

/** 助手消息：左对齐通栏（不套气泡），白底透明，15px 行高 1.7。
 *  带思考流/trace 快照时先渲染「深度思考」「执行过程」折叠区（默认收起），正文在后。 */
export function AssistantMessage({ content, tools, todos, durationMs, reasoning }: { content: string; tools?: Message['tools']; todos?: Message['todos']; durationMs?: Message['durationMs']; reasoning?: string }) {
  const done = tools?.filter((t) => t.status !== 'running').length ?? 0
  const durationText = durationMs ? ` · ${formatDuration(durationMs)}` : ''
  return (
    <AssistantFrame>
      {reasoning?.trim() && <DeepThinking text={reasoning} />}
      {tools && tools.length > 0 && (
        <Reasoning isStreaming={false} className="mb-1.5">
          <ReasoningTrigger className="text-sm text-foreground">
            执行过程 · {tools.length} 步{durationText}
          </ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2">
            <RunTrace tools={tools} todos={todos ?? []} done={done} total={tools.length} />
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
      durationMs={message.durationMs}
      reasoning={message.reasoning}
    />
  )
}
