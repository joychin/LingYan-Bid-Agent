import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message } from '@/api/client'
import { Message as WMessage } from '@/components/workspace/Message'

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

/** 助手消息：左对齐通栏（不套气泡），白底透明，15px 行高 1.7。 */
export function AssistantMessage({ content }: { content: string }) {
  return (
    <AssistantFrame>
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
    <AssistantMessage content={message.content} />
  )
}
