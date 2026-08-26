import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message } from '@/api/client'
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai/Reasoning'
import { RunTrace } from '@/components/ai/RunTrace'
import { Message as WMessage } from '@/components/workspace/Message'
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

/** 助手消息：左对齐通栏（不套气泡），白底透明，15px 行高 1.7。
 *  带 trace 快照时先渲染「执行过程」折叠区（默认收起，标题含步数与总耗时），正文在后。 */
export function AssistantMessage({ content, tools, todos, durationMs }: { content: string; tools?: Message['tools']; todos?: Message['todos']; durationMs?: Message['durationMs'] }) {
  const done = tools?.filter((t) => t.status !== 'running').length ?? 0
  const durationText = durationMs ? ` · ${formatDuration(durationMs)}` : ''
  return (
    <AssistantFrame>
      {tools && tools.length > 0 && (
        <Reasoning isStreaming={false} className="mb-2">
          <ReasoningTrigger className="text-sm text-foreground">
            执行过程 · {tools.length} 步{durationText}
          </ReasoningTrigger>
          <ReasoningContent contentClassName="mt-2">
            <RunTrace tools={tools} todos={todos ?? []} done={done} total={tools.length} />
          </ReasoningContent>
        </Reasoning>
      )}
      <div className="bubble">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
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
    <AssistantMessage content={message.content} tools={message.tools} todos={message.todos} durationMs={message.durationMs} />
  )
}
